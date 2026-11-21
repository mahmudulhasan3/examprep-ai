from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ExamCreateRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=100)
    num_questions: int = Field(default=5, ge=1, le=10)
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class GeneratedQuestion(BaseModel):
    """One question as produced by the AI. Also used as the structured-output schema."""

    question_text: str
    model_answer: str


class GeneratedExam(BaseModel):
    questions: list[GeneratedQuestion]


class QuestionOut(BaseModel):
    """What the student sees. The model answer is deliberately not included."""

    id: int
    question_text: str


class ExamDetail(BaseModel):
    id: int
    title: str
    difficulty: str
    num_questions: int
    questions: list[QuestionOut]


class ExamSummary(BaseModel):
    id: int
    title: str
    difficulty: str
    num_questions: int
    created_at: datetime
    model_config = {"from_attributes": True}
