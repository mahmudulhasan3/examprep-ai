from types import SimpleNamespace

import pytest

from app.schemas.exam import GeneratedExam, GeneratedQuestion


def get_auth_token(client, email="exam@example.com", password="testpass123"):
    client.post("/auth/register", json={"email": email, "password": password})
    response = client.post("/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def mock_exam_generator(monkeypatch):
    def fake(topic, num_questions, difficulty):
        return [
            GeneratedQuestion(
                question_text=f"Question {i} about {topic}?",
                model_answer=f"Model answer {i}",
            )
            for i in range(1, num_questions + 1)
        ]

    monkeypatch.setattr("app.routers.exams.generate_exam_questions", fake)


def test_create_exam_returns_questions_without_answers(client):
    token = get_auth_token(client)
    response = client.post(
        "/exams",
        json={"topic": "Genetic Algorithm", "num_questions": 3, "difficulty": "hard"},
        headers=auth(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Genetic Algorithm"
    assert data["difficulty"] == "hard"
    assert data["num_questions"] == 3
    assert len(data["questions"]) == 3
    for question in data["questions"]:
        assert set(question.keys()) == {"id", "question_text"}
    assert "Model answer" not in response.text


def test_model_answers_are_stored_in_database(client):
    token = get_auth_token(client)
    client.post(
        "/exams",
        json={"topic": "Search Algorithms", "num_questions": 2},
        headers=auth(token),
    )

    from tests.conftest import TestingSessionLocal
    from app.db.models import Question

    with TestingSessionLocal() as db:
        answers = [q.model_answer for q in db.query(Question).order_by(Question.id)]
    assert answers == ["Model answer 1", "Model answer 2"]


def test_create_exam_requires_login(client):
    response = client.post("/exams", json={"topic": "Genetic Algorithm"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"topic": "ab"},
        {"topic": "x" * 101},
        {"topic": "Valid topic", "num_questions": 0},
        {"topic": "Valid topic", "num_questions": 11},
        {"topic": "Valid topic", "difficulty": "impossible"},
    ],
)
def test_create_exam_validation(client, payload):
    token = get_auth_token(client)
    response = client.post("/exams", json=payload, headers=auth(token))
    assert response.status_code == 422


def test_ai_failure_returns_502_and_saves_nothing(client, monkeypatch):
    def boom(topic, num_questions, difficulty):
        raise RuntimeError("gemini down")

    monkeypatch.setattr("app.routers.exams.generate_exam_questions", boom)
    token = get_auth_token(client)
    response = client.post(
        "/exams", json={"topic": "Genetic Algorithm"}, headers=auth(token)
    )
    assert response.status_code == 502
    assert client.get("/exams", headers=auth(token)).json() == []


def test_list_exams_newest_first(client):
    token = get_auth_token(client)
    client.post("/exams", json={"topic": "First topic"}, headers=auth(token))
    client.post("/exams", json={"topic": "Second topic"}, headers=auth(token))
    response = client.get("/exams", headers=auth(token))
    assert response.status_code == 200
    assert [e["title"] for e in response.json()] == ["Second topic", "First topic"]


def test_get_exam_detail_keeps_question_order(client):
    token = get_auth_token(client)
    created = client.post(
        "/exams",
        json={"topic": "Ordered topic", "num_questions": 4},
        headers=auth(token),
    ).json()
    response = client.get(f"/exams/{created['id']}", headers=auth(token))
    assert response.status_code == 200
    texts = [q["question_text"] for q in response.json()["questions"]]
    assert texts == [f"Question {i} about Ordered topic?" for i in range(1, 5)]


def test_other_users_exam_is_404(client):
    token_a = get_auth_token(client, "owner@example.com")
    created = client.post(
        "/exams", json={"topic": "Private exam"}, headers=auth(token_a)
    ).json()
    token_b = get_auth_token(client, "other@example.com")
    response = client.get(f"/exams/{created['id']}", headers=auth(token_b))
    assert response.status_code == 404


def test_generate_exam_questions_parses_structured_output(monkeypatch):
    from app.core import gemini_client

    parsed = GeneratedExam(
        questions=[
            GeneratedQuestion(question_text=f"Q{i}", model_answer=f"A{i}")
            for i in range(5)
        ]
    )
    fake_models = SimpleNamespace(
        generate_content=lambda **kwargs: SimpleNamespace(parsed=parsed)
    )
    monkeypatch.setattr(gemini_client, "client", SimpleNamespace(models=fake_models))

    result = gemini_client.generate_exam_questions("Topic", 3, "easy")
    assert [q.question_text for q in result] == ["Q0", "Q1", "Q2"]


def test_generate_exam_questions_rejects_empty_output(monkeypatch):
    from app.core import gemini_client

    fake_models = SimpleNamespace(
        generate_content=lambda **kwargs: SimpleNamespace(parsed=None)
    )
    monkeypatch.setattr(gemini_client, "client", SimpleNamespace(models=fake_models))

    with pytest.raises(ValueError):
        gemini_client.generate_exam_questions("Topic", 3, "easy")
