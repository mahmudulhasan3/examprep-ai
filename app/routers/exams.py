import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.gemini_client import generate_exam_questions, grade_answers
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import Answer, Exam, Question, Result
from app.schemas.exam import (
    MAX_SCORE_PER_QUESTION,
    ExamCreateRequest,
    ExamDetail,
    ExamResultOut,
    ExamSummary,
    SubmitRequest,
)

logger = logging.getLogger(__name__)

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


def get_owned_exam(db: Session, exam_id: int, user_id: int) -> Exam:
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.user_id == user_id).first()
    if exam is None:
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam


def get_questions(db: Session, exam: Exam) -> list[Question]:
    return (
        db.query(Question)
        .filter(Question.exam_id == exam.id)
        .order_by(Question.id)
        .all()
    )


def build_result(db: Session, exam: Exam) -> dict:
    """Result view. Here the model answers are revealed, because the exam is over."""
    result = db.query(Result).filter(Result.exam_id == exam.id).first()
    if result is None:
        raise HTTPException(status_code=404, detail="Exam has not been submitted yet")

    questions = get_questions(db, exam)
    answers = {
        a.question_id: a
        for a in db.query(Answer)
        .filter(Answer.question_id.in_([q.id for q in questions]))
        .all()
    }
    return {
        "exam_id": exam.id,
        "title": exam.title,
        "total_score": result.total_score,
        "max_score": MAX_SCORE_PER_QUESTION * len(questions),
        "percentage": result.percentage,
        "overall_feedback": result.overall_feedback,
        "answers": [
            {
                "question_id": q.id,
                "question_text": q.question_text,
                "user_answer": answers[q.id].user_answer,
                "model_answer": q.model_answer,
                "score": answers[q.id].score,
                "feedback": answers[q.id].feedback,
            }
            for q in questions
            if q.id in answers
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
        logger.exception("Exam generation failed")
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
    exam = get_owned_exam(db, exam_id, user_id)
    return exam_detail(exam, get_questions(db, exam))


@router.post("/{exam_id}/submit", response_model=ExamResultOut)
def submit_exam(
    exam_id: int,
    request: SubmitRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    exam = get_owned_exam(db, exam_id, user_id)

    if db.query(Result).filter(Result.exam_id == exam.id).first() is not None:
        raise HTTPException(status_code=409, detail="This exam is already submitted")

    questions = get_questions(db, exam)

    submitted: dict[int, str] = {}
    for item in request.answers:
        if item.question_id in submitted:
            raise HTTPException(
                status_code=400, detail="Duplicate answer for a question"
            )
        submitted[item.question_id] = item.answer_text

    if set(submitted) != {q.id for q in questions}:
        raise HTTPException(
            status_code=400,
            detail="Answer every question of this exam exactly once",
        )

    grading_input = [
        {
            "question_id": q.id,
            "question": q.question_text,
            "model_answer": q.model_answer,
            "student_answer": submitted[q.id],
        }
        for q in questions
    ]

    try:
        grading = grade_answers(grading_input)
    except Exception:
        logger.exception("Grading failed")
        raise HTTPException(
            status_code=502, detail="AI service is unavailable. Try again."
        )

    graded = {g.question_id: g for g in grading.graded}
    if len(grading.graded) != len(questions) or set(graded) != set(submitted):
        logger.error("Grading result does not match the submitted questions")
        raise HTTPException(
            status_code=502, detail="AI returned an incomplete grading. Try again."
        )

    total = 0
    for q in questions:
        # never trust the model to stay inside the allowed range
        score = max(0, min(MAX_SCORE_PER_QUESTION, graded[q.id].score))
        total += score
        db.add(
            Answer(
                question_id=q.id,
                user_answer=submitted[q.id],
                score=score,
                feedback=graded[q.id].feedback,
            )
        )

    max_total = MAX_SCORE_PER_QUESTION * len(questions)
    db.add(
        Result(
            exam_id=exam.id,
            total_score=total,
            percentage=round(total / max_total * 100, 1),
            overall_feedback=grading.overall_feedback,
        )
    )

    try:
        db.commit()
    except IntegrityError:
        # two submits raced; the unique constraints let only one win
        db.rollback()
        raise HTTPException(status_code=409, detail="This exam is already submitted")

    return build_result(db, exam)


@router.get("/{exam_id}/result", response_model=ExamResultOut)
def get_result(
    exam_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    exam = get_owned_exam(db, exam_id, user_id)
    return build_result(db, exam)
