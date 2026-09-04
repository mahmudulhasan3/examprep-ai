from fastapi import APIRouter, Depends, HTTPException
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    AuthChatRequest,
    AuthChatResponse,
)
from app.core.memory_store import guest_sessions
from app.core.gemini_client import generate_chat_response
from app.db.database import get_db
from app.core.security import get_current_user
from sqlalchemy.orm import Session
from app.db.models import ChatSession, ChatMessage
import uuid

router = APIRouter(prefix="/chat")


@router.post("/guest", response_model=ChatResponse, tags=["Guest Chat"])
def guest(request: ChatRequest):

    if request.session_id:
        session_id = request.session_id

    else:
        session_id = str(uuid.uuid4())

    history = guest_sessions.get(session_id, [])

    history.append({"role": "user", "content": request.message})

    reply = generate_chat_response(history)

    history.append({"role": "assistant", "content": reply})

    guest_sessions[session_id] = history

    return {"session_id": session_id, "reply": reply}


@router.post(
    "/authenticated", response_model=AuthChatResponse, tags=["Authenticated Chat"]
)
def authenticated_chat(
    request: AuthChatRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    if request.session_id:
        session = (
            db.query(ChatSession)
            .filter(
                ChatSession.id == request.session_id, ChatSession.user_id == user_id
            )
            .first()
        )

        if session is None:
            raise HTTPException(status_code=404, detail="Chat session not found")
    else:
        session = ChatSession(user_id=user_id)
        db.add(session)
        db.commit()
        db.refresh(session)

    history = []
    for msg in session.messages:
        history.append({"role": msg.role, "content": msg.content})

    user_message = ChatMessage(
        chat_session_id=session.id,
        role="user",
        content=request.message,
    )
    db.add(user_message)
    db.commit()

    history.append({"role": "user", "content": request.message})
    reply = generate_chat_response(history)

    ai_message = ChatMessage(
        chat_session_id=session.id,
        role="assistant",
        content=reply,
    )
    db.add(ai_message)
    db.commit()

    return {"session_id": session.id, "reply": reply}
