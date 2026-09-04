from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str


class AuthChatRequest(BaseModel):
    message: str
    session_id: int | None = None


class AuthChatResponse(BaseModel):
    session_id: int
    reply: str