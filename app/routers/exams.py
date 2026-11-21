from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.gemini_client import generate_exam_questions
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import Exam, Question
from app.schemas.exam import ExamCreateRequest, ExamDetail, ExamSummary

router = APIRouter(prefix="/exams", tags=["Exams"])


def exam_detail(exam: Exam, questions: list[Question]) -> dict:
    """Build the student-facing view. Model answers never leave the server here."""
    return {
        "id": exam.id,
        "title": exam.title,
        "difficulty": exam.difficulty,
        "num_questions": exam.num_questions,
        "questions": [
            {"id": q.id, "question_text": q.question_text} for q in questions
        ],
    }


@router.post("", response_model=ExamDetail, status_code=201)
def create_exam(
    request: ExamCreateRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    try:
        generated = generate_exam_questions(
            request.topic.strip(), request.num_questions, request.difficulty
        )
    except Exception:
        raise HTTPException(
            status_code=502, detail="AI service is unavailable. Try again."
        )

    exam = Exam(
        user_id=user_id,
        title=request.topic.strip(),
        difficulty=request.difficulty,
        num_questions=len(generated),
    )
    db.add(exam)
    db.flush()  # get exam.id before inserting the questions

    questions = [
        Question(
            exam_id=exam.id,
            question_text=item.question_text,
            model_answer=item.model_answer,
        )
        for item in generated
    ]
    db.add_all(questions)
    db.commit()

    return exam_detail(exam, questions)


@router.get("", response_model=list[ExamSummary])
def list_exams(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    return db.query(Exam).filter(Exam.user_id == user_id).order_by(Exam.id.desc()).all()


@router.get("/{exam_id}", response_model=ExamDetail)
def get_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.user_id == user_id).first()
    if exam is None:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = (
        db.query(Question)
        .filter(Question.exam_id == exam.id)
        .order_by(Question.id)
        .all()
    )
    return exam_detail(exam, questions)
