import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.gemini_client import generate_chat_response, stream_chat_response
from app.core.memory_store import guest_sessions
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import ChatMessage, ChatSession
from app.schemas.chat import (
    AuthChatRequest,
    AuthChatResponse,
    ChatRequest,
    ChatResponse,
    SessionDetail,
    SessionSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat")

AI_UNAVAILABLE = "AI service is unavailable. Try again."


def get_or_create_session(
    db: Session, session_id: int | None, first_message: str, user_id: int
) -> tuple[ChatSession, bool]:
    """Return the user's session, or start a new one. The bool says if it is new.

    A new session is only flushed, not committed: flush() gives it an id, and if the
    AI call fails nothing reaches the database.
    """
    if session_id:
        session = (
            db.query(ChatSession)
            .filter(ChatSession.id == session_id, ChatSession.user_id == user_id)
            .first()
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Chat session not found")
        return session, False

    session = ChatSession(user_id=user_id, title=first_message.strip()[:50])
    db.add(session)
    db.flush()
    return session, True


def history_of(session: ChatSession) -> list[dict]:
    return [{"role": msg.role, "content": msg.content} for msg in session.messages]


def ndjson(event: dict) -> str:
    """One streaming event as a single JSON line."""
    return json.dumps(event, ensure_ascii=False) + "\n"


def open_stream(history: list[dict]):
    """Start the AI stream and read its first piece.

    Doing this before the response starts means a failure becomes a normal 502
    instead of a broken half-sent stream.
    """
    stream = stream_chat_response(history)
    try:
        first = next(stream)
    except StopIteration:
        logger.error("The AI returned an empty reply")
        raise HTTPException(status_code=502, detail=AI_UNAVAILABLE)
    except Exception:
        logger.exception("Could not start the AI stream")
        raise HTTPException(status_code=502, detail=AI_UNAVAILABLE)
    return first, stream


def stream_events(first, stream, on_complete, on_abort):
    """Turn the AI pieces into NDJSON events: delta..., then done (or error).

    on_complete(full_reply) saves the result; on_abort() cleans up when the stream
    ends early (AI error, save error, or the client closed the connection).
    """
    parts = [first]
    completed = False
    try:
        yield ndjson({"type": "delta", "text": first})
        for text in stream:
            parts.append(text)
            yield ndjson({"type": "delta", "text": text})
        on_complete("".join(parts))
        completed = True
        yield ndjson({"type": "done"})
    except Exception:
        logger.exception("Chat stream failed")
        yield ndjson(
            {"type": "error", "detail": "The reply was interrupted. Try again."}
        )
    finally:
        if not completed:
            on_abort()


@router.post("/guest", response_model=ChatResponse, tags=["Guest Chat"])
def guest(request: ChatRequest):

    if request.session_id:
        session_id = request.session_id

    else:
        session_id = str(uuid.uuid4())

    history = guest_sessions.get(session_id, [])

    history.append({"role": "user", "content": request.message})

    try:
        reply = generate_chat_response(history)
    except Exception:
        logger.exception("Guest chat: Gemini call failed")
        history.pop()  # remove the failed user message so the history stays clean
        raise HTTPException(status_code=502, detail=AI_UNAVAILABLE)

    history.append({"role": "assistant", "content": reply})

    guest_sessions[session_id] = history

    return {"session_id": session_id, "reply": reply}


@router.post("/guest/stream", tags=["Guest Chat"])
def guest_stream(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    history = list(guest_sessions.get(session_id, []))
    history.append({"role": "user", "content": request.message})

    first, stream = open_stream(history)

    def on_complete(reply: str):
        guest_sessions[session_id] = history + [{"role": "assistant", "content": reply}]

    return StreamingResponse(
        stream_events(first, stream, on_complete, lambda: None),
        media_type="application/x-ndjson",
        headers={"X-Session-Id": session_id},
    )


@router.post(
    "/authenticated", response_model=AuthChatResponse, tags=["Authenticated Chat"]
)
def authenticated_chat(
    request: AuthChatRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    session, _ = get_or_create_session(db, request.session_id, request.message, user_id)

    history = history_of(session)
    history.append({"role": "user", "content": request.message})

    # Call the AI first; save both messages only if it succeeds
    try:
        reply = generate_chat_response(history)
    except Exception:
        logger.exception("Authenticated chat: Gemini call failed")
        raise HTTPException(status_code=502, detail=AI_UNAVAILABLE)

    db.add(
        ChatMessage(chat_session_id=session.id, role="user", content=request.message)
    )
    db.add(ChatMessage(chat_session_id=session.id, role="assistant", content=reply))
    db.commit()

    return {"session_id": session.id, "reply": reply}


@router.post("/authenticated/stream", tags=["Authenticated Chat"])
def authenticated_stream(
    request: AuthChatRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    session, is_new = get_or_create_session(
        db, request.session_id, request.message, user_id
    )
    session_id = session.id  # keep a plain int; the ORM object may be detached later

    history = history_of(session)
    history.append({"role": "user", "content": request.message})

    first, stream = open_stream(history)

    if is_new:
        # The AI answered, so make the session durable before the stream starts.
        db.commit()

    def on_complete(reply: str):
        db.add(
            ChatMessage(
                chat_session_id=session_id, role="user", content=request.message
            )
        )
        db.add(ChatMessage(chat_session_id=session_id, role="assistant", content=reply))
        db.commit()

    def on_abort():
        # A brand-new chat that never finished should not stay behind as an empty row.
        if is_new:
            db.rollback()
            db.query(ChatSession).filter(ChatSession.id == session_id).delete()
            db.commit()

    return StreamingResponse(
        stream_events(first, stream, on_complete, on_abort),
        media_type="application/x-ndjson",
        headers={"X-Session-Id": str(session_id)},
    )


@router.get(
    "/sessions", response_model=list[SessionSummary], tags=["Authenticated Chat"]
)
def list_sessions(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    return (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user_id)
        .order_by(ChatSession.id.desc())
        .all()
    )


@router.get(
    "/sessions/{session_id}",
    response_model=SessionDetail,
    tags=["Authenticated Chat"],
)
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == user_id)
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session
