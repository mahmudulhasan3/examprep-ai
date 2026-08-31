from fastapi import APIRouter
from app.schemas.chat import ChatRequest, ChatResponse
from app.core.memory_store import guest_sessions
from app.core.gemini_client import generate_chat_response
import uuid

router = APIRouter(prefix="/chat", tags=["Guest Chat"])


@router.post("/guest", response_model=ChatResponse)
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
