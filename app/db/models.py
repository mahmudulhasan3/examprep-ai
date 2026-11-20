from datetime import datetime
from sqlalchemy import String, func, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(back_populates="user")
    exams: Mapped[list["Exam"]] = relationship(back_populates="user")


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    user: Mapped["User"] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="chat_session", order_by="ChatMessage.id"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    chat_session: Mapped["ChatSession"] = relationship(back_populates="messages")


class Exam(Base):
    __tablename__ = "exams"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    source_pdf_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    num_questions: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    user: Mapped["User"] = relationship(back_populates="exams")
    questions: Mapped[list["Question"]] = relationship(back_populates="exam")
    result: Mapped["Result"] = relationship(back_populates="exam")


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    answer: Mapped["Answer"] = relationship(back_populates="question")
    exam: Mapped["Exam"] = relationship(back_populates="questions")


class Answer(Base):
    __tablename__ = "answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id"), nullable=False, unique=True
    )
    user_answer: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int] = mapped_column(nullable=False)
    feedback: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    question: Mapped["Question"] = relationship(back_populates="answer")


class Result(Base):
    __tablename__ = "results"
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id"), nullable=False, unique=True
    )
    total_score: Mapped[int] = mapped_column(nullable=False)
    percentage: Mapped[float] = mapped_column(nullable=False)
    overall_feedback: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    exam: Mapped["Exam"] = relationship(back_populates="result")
