import logging

from fastapi import FastAPI

from app.core.security import SECRET_KEY
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.exams import router as exams_router

logger = logging.getLogger(__name__)

if len(SECRET_KEY) < 32:
    logger.warning(
        "SECRET_KEY is shorter than 32 characters. Use a long random value, for "
        'example: python -c "import secrets; print(secrets.token_urlsafe(48))"'
    )

app = FastAPI()

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(exams_router)


@app.get("/")
def root():
    return {"message": "ExamPrep AI API is running"}
