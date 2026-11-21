from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

MAX_SCORE_PER_QUESTION = 10

AnswerText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]


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
    percentage: float | None = None  # None until the exam is submitted
    model_config = {"from_attributes": True}


class AnswerIn(BaseModel):
    question_id: int
    answer_text: AnswerText


class SubmitRequest(BaseModel):
    answers: list[AnswerIn] = Field(min_length=1)


class GradedAnswer(BaseModel):
    """One graded answer as produced by the AI. Part of the structured-output schema."""

    question_id: int
    score: int
    feedback: str


class GradingResult(BaseModel):
    graded: list[GradedAnswer]
    overall_feedback: str


class AnswerResultOut(BaseModel):
    """After submission the model answer is revealed, so the student can learn from it."""

    question_id: int
    question_text: str
    user_answer: str
    model_answer: str
    score: int
    feedback: str


class ExamResultOut(BaseModel):
    exam_id: int
    title: str
    total_score: int
    max_score: int
    percentage: float
    overall_feedback: str
    answers: list[AnswerResultOut]
