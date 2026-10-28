import shutil

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.ingestion import cloner
from app.llm.provider import LLMConfigError
from app.main import app
from app.rag import chain

URL = "https://github.com/octo/sample"


@pytest.fixture
def client(sample_repo, monkeypatch):
    def fake_clone(url, destination):
        shutil.copytree(sample_repo, destination, dirs_exist_ok=True)
        return "abc1234"

    monkeypatch.setattr(cloner, "clone_or_pull", fake_clone)
    return TestClient(app)


@pytest.fixture
def fake_llm(monkeypatch):
    llm = FakeListChatModel(responses=["Login lives in [app/auth.py:1-12]."])
    monkeypatch.setattr(chain, "get_llm", lambda: llm)


def index(client):
    response = client.post("/api/repos", json={"url": URL})
    assert response.status_code == 202
    return response.json()["id"]


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_index_repo_end_to_end(client):
    repo_id = index(client)
    repo = client.get(f"/api/repos/{repo_id}").json()
    assert repo["status"] == "ready"
    assert repo["files"] == 4
    assert repo["chunks"] >= 5
    assert repo["commit_sha"] == "abc1234"
    assert [r["id"] for r in client.get("/api/repos").json()] == [repo_id]


def test_invalid_url_is_rejected(client):
    assert client.post("/api/repos", json={"url": "file:///etc/passwd"}).status_code == 400


def test_failed_index_reports_error(client, monkeypatch):
    def boom(url, destination):
        raise RuntimeError("repository not found")

    monkeypatch.setattr(cloner, "clone_or_pull", boom)
    repo_id = client.post("/api/repos", json={"url": URL}).json()["id"]
    repo = client.get(f"/api/repos/{repo_id}").json()
    assert repo["status"] == "failed"
    assert "repository not found" in repo["error"]


def test_chat_returns_answer_and_sources(client, fake_llm):
    repo_id = index(client)
    response = client.post(f"/api/repos/{repo_id}/chat", json={"question": "How does login work?"})
    assert response.status_code == 200
    body = response.json()
    assert "app/auth.py" in body["answer"]
    assert body["sources"]
    assert all({"label", "path", "start_line", "snippet"} <= set(s) for s in body["sources"])


def test_chat_context_never_contains_secret_values(client, monkeypatch):
    seen = {}

    class Spy(FakeListChatModel):
        def _call(self, messages, *args, **kwargs):
            seen["prompt"] = " ".join(str(m.content) for m in messages)
            return super()._call(messages, *args, **kwargs)

    monkeypatch.setattr(chain, "get_llm", lambda: Spy(responses=["ok"]))
    repo_id = index(client)
    client.post(f"/api/repos/{repo_id}/chat", json={"question": "What is SECRET_KEY in config.py?"})
    assert "hunter2hunter2" not in seen["prompt"]
    assert "[REDACTED]" in seen["prompt"]


def test_overview_question_includes_repo_overview(client, fake_llm):
    repo_id = index(client)
    question = "Give me an overview of this repo"
    body = client.post(f"/api/repos/{repo_id}/chat", json={"question": question}).json()
    assert body["sources"][0]["label"] == "(repository overview)"


def test_chat_unknown_repo_is_404(client):
    assert client.post("/api/repos/nope/chat", json={"question": "hello there"}).status_code == 404


def test_chat_before_ready_is_409(client):
    from app import store

    store.upsert_repo("octo__sample", URL, "octo", "sample", status="indexing")
    assert client.post("/api/repos/octo__sample/chat", json={"question": "hello there"}).status_code == 409


def test_missing_api_key_gives_503(client, monkeypatch):
    def no_key():
        raise LLMConfigError("GOOGLE_API_KEY is not set. Add it to your .env file.")

    monkeypatch.setattr(chain, "get_llm", no_key)
    repo_id = index(client)
    response = client.post(f"/api/repos/{repo_id}/chat", json={"question": "How does login work?"})
    assert response.status_code == 503
    assert "GOOGLE_API_KEY" in response.json()["detail"]


def test_semantic_search_without_llm(client):
    repo_id = index(client)
    response = client.get(f"/api/repos/{repo_id}/search", params={"q": "is_low_stock", "language": "python"})
    assert response.status_code == 200
    assert response.json()[0]["path"] == "app/inventory.py"


def test_health_reports_whether_key_is_configured(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert client.get("/health").json()["llm_key_configured"] is False
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key")
    body = client.get("/health").json()
    assert body["llm_key_configured"] is True
    assert "dummy-key" not in str(body)
