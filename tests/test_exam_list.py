import pytest

from app.schemas.exam import GeneratedQuestion, GradedAnswer, GradingResult


def get_auth_token(client, email="list@example.com", password="testpass123"):
    client.post("/auth/register", json={"email": email, "password": password})
    response = client.post("/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def mock_ai(monkeypatch):
    def fake_generate(topic, num_questions, difficulty):
        return [
            GeneratedQuestion(question_text=f"Q{i}?", model_answer=f"A{i}")
            for i in range(1, num_questions + 1)
        ]

    def fake_grade(items):
        return GradingResult(
            graded=[
                GradedAnswer(question_id=i["question_id"], score=7, feedback="ok")
                for i in items
            ],
            overall_feedback="fine",
        )

    monkeypatch.setattr("app.routers.exams.generate_exam_questions", fake_generate)
    monkeypatch.setattr("app.routers.exams.grade_answers", fake_grade)


def test_list_shows_percentage_only_after_submit(client):
    token = get_auth_token(client)
    submitted_exam = client.post(
        "/exams",
        json={"topic": "Submitted one", "num_questions": 2},
        headers=auth(token),
    ).json()
    client.post(
        "/exams", json={"topic": "Open one", "num_questions": 2}, headers=auth(token)
    )

    client.post(
        f"/exams/{submitted_exam['id']}/submit",
        json={
            "answers": [
                {"question_id": q["id"], "answer_text": "answer"}
                for q in submitted_exam["questions"]
            ]
        },
        headers=auth(token),
    )

    exams = client.get("/exams", headers=auth(token)).json()
    by_title = {e["title"]: e["percentage"] for e in exams}
    assert by_title == {"Open one": None, "Submitted one": 70.0}
    assert [e["title"] for e in exams] == ["Open one", "Submitted one"]
