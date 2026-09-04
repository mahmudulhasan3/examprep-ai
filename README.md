# ExamPrep AI

An AI-powered study assistant backend built with FastAPI, featuring JWT
authentication and Gemini-powered conversational AI chat — available both as a
guest (temporary) and as a logged-in user (persistent history).

This project was built as a hands-on learning exercise in professional backend
development practices: clean architecture, secure authentication, database
design with SQLAlchemy 2.0, and integrating a third-party LLM API into a real
request/response flow.

## Features

- **JWT Authentication** — Secure user registration and login using `pwdlib`
  (bcrypt) for password hashing and `PyJWT` for token issuance/verification.
- **Guest AI Chat** — Chat with the AI without an account. Conversation history
  is kept in-memory for the duration of the session and is not persisted.
- **Authenticated AI Chat** — Logged-in users get persistent conversation
  history stored in PostgreSQL. Each user can maintain multiple independent chat
  sessions, and can only access their own sessions (authorization enforced at
  the query level).
- **Context-aware conversations** — Both guest and authenticated chat maintain
  conversation history so the AI can understand follow-up questions.

## Tech Stack

| Layer            | Technology                                               |
| ---------------- | -------------------------------------------------------- |
| Framework        | FastAPI                                                  |
| Database         | PostgreSQL                                               |
| ORM              | SQLAlchemy 2.0 (modern `Mapped` / `mapped_column` style) |
| Validation       | Pydantic                                                 |
| Authentication   | JWT (PyJWT)                                              |
| Password Hashing | pwdlib (bcrypt)                                          |
| AI / LLM         | Google Gemini API                                        |
| Config           | python-dotenv                                            |

## Project Structure

```
app/
├── core/
│   ├── security.py         # password hashing, JWT create/decode, get_current_user dependency
│   ├── gemini_client.py     # Gemini API integration
│   ├── memory_store.py      # in-memory storage for guest chat sessions
│   └── env_utils.py         # shared .env variable loader
├── db/
│   ├── database.py          # SQLAlchemy engine, session, Base
│   ├── models.py            # User, ChatSession, ChatMessage, Exam, Question, Answer, Result
│   └── init_db.py           # table creation script
├── schemas/
│   ├── user.py               # Pydantic schemas for auth
│   └── chat.py               # Pydantic schemas for chat
├── routers/
│   ├── auth.py                # /auth/register, /auth/login
│   └── chat.py                # /chat/guest, /chat/authenticated
└── main.py                    # FastAPI app entrypoint
```

## Database Schema

The data model is designed to support the full planned feature set (see
[Roadmap](#roadmap) below), even though not all of it is wired up to endpoints
yet:

```
User
 ├──< ChatSession ──< ChatMessage
 └──< Exam ──< Question ──── Answer
          └──── Result
```

## API Endpoints

| Method | Endpoint              | Auth Required      | Description                                     |
| ------ | --------------------- | ------------------ | ----------------------------------------------- |
| POST   | `/auth/register`      | No                 | Create a new user account                       |
| POST   | `/auth/login`         | No                 | Authenticate and receive a JWT access token     |
| POST   | `/chat/guest`         | No                 | Chat with the AI as a guest (temporary session) |
| POST   | `/chat/authenticated` | Yes (Bearer token) | Chat with the AI with persistent history        |

### Example: Register

```json
POST /auth/register
{
  "email": "user@example.com",
  "password": "yourpassword"
}
```

### Example: Authenticated Chat

```json
POST /chat/authenticated
Authorization: Bearer <access_token>

{
  "message": "Explain Newton's First Law",
  "session_id": null
}
```

Response:

```json
{
  "session_id": 1,
  "reply": "Newton's First Law states that..."
}
```

Omit `session_id` (or set it to `null`) to start a new conversation. Pass the
`session_id` returned from a previous response to continue that same
conversation with full context.

## Setup Instructions

### 1. Clone and set up the environment

```bash
git clone <your-repo-url>
cd ExamPrep
python -m venv .venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set up PostgreSQL

Create a database and a user with access to it (via `psql` or pgAdmin).

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in your own values:

```bash
cp .env.example .env
```

### 4. Create the database tables

```bash
python -m app.db.init_db
```

### 5. Run the server

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`, with interactive docs at
`http://127.0.0.1:8000/docs`.

## Roadmap

This is being developed iteratively. Planned next steps:

- [ ] PDF upload and text extraction
- [ ] RAG pipeline (chunking, embeddings, vector search) for grounded question
      generation
- [ ] AI-generated exams/quizzes from uploaded material
- [ ] AI-based answer evaluation with scoring and feedback
- [ ] Exam result history and dashboard
- [ ] Alembic migrations, structured logging, and token/cost tracking

## Notes

This project was built as a guided learning exercise, with an emphasis on
understanding _why_ each design decision was made (e.g., password hashing vs.
plaintext, JWT payload design, authorization checks on shared resources) rather
than just producing working code.
