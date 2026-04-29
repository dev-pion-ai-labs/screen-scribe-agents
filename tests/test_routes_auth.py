"""Smoke tests: every protected route returns 401 without a bearer token."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_notes_generate_requires_auth():
    r = client.post("/api/notes/generate", json={"subtopic": "film analysis"})
    assert r.status_code == 401


def test_assignments_generate_requires_auth():
    r = client.post("/api/assignments/generate", json={"subtopic": "film analysis"})
    assert r.status_code == 401


def test_assignments_revise_requires_auth():
    r = client.post(
        "/api/assignments/revise",
        json={"subtopic": "film analysis", "content": "x", "changes": "y"},
    )
    assert r.status_code == 401


def test_quizzes_generate_requires_auth():
    r = client.post("/api/quizzes/generate", json={"subtopic": "film analysis"})
    assert r.status_code == 401
