from datetime import datetime
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str


class AuthChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: int | None = None


class AuthChatResponse(BaseModel):
    session_id: int
    reply: str


class MessageOut(BaseModel):
    role: str
    content: str
    model_config = {"from_attributes": True}


class SessionSummary(BaseModel):
    id: int
    title: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class SessionDetail(BaseModel):
    id: int
    title: str | None
    messages: list[MessageOut]
    model_config = {"from_attributes": True}
