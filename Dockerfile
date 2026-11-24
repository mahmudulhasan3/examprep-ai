# syntax=docker/dockerfile:1

# ---------- base: the runtime dependencies ----------
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy only the requirements first, so this layer is cached until they change.
COPY requirements.txt .
RUN pip install -r requirements.txt


# ---------- test: run the test suite inside the image ----------
FROM base AS test

COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt

# Dummy values: the tests use an in-memory database and fake AI replies.
ENV DATABASE_URL=postgresql://user:password@localhost:5432/test \
    SECRET_KEY=test-secret-key-used-only-inside-the-test-stage-0123456789 \
    ALGORITHM=HS256 \
    ACCESS_TOKEN_EXPIRE_MINUTES=30 \
    GEMINI_API_KEY=test-key \
    GEMINI_MODEL_NAME=test-model

COPY app ./app
COPY tests ./tests

CMD ["python", "-m", "pytest", "-q"]


# ---------- runtime: the image that actually runs the API ----------
FROM base AS runtime

# Run as a normal user, not as root.
RUN useradd --create-home --uid 10001 appuser

COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
# One worker on purpose: the rate limits and guest chats are kept in this process.
# Render and similar platforms set PORT; locally it falls back to 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]