import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm import provider
from app.pipeline import routes
from app.pipeline.github_client import GitHubError
from tests.pipeline_helpers import (
    REPO_ID,
    FakeGitHub,
    index_repo,
    make_llm,
    register_repo,
)

BASE = f"/api/repos/{REPO_ID}/pipeline"


@pytest.fixture
def api(monkeypatch, sample_repo):
    monkeypatch.setenv("PIPELINE_POLL_SECONDS", "0")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    register_repo()
    index_repo(sample_repo)
    fake = FakeGitHub()
    monkeypatch.setattr(routes, "get_client", lambda: fake)
    monkeypatch.setattr(provider, "get_llm", lambda: make_llm())
    application = FastAPI()
    application.include_router(routes.router)
    client = TestClient(application)
    client.fake = fake
    return client


def test_status_reports_whether_a_token_is_configured(api, monkeypatch):
    assert api.get(f"{BASE}/status").json()["github_token_configured"] is False
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake_secret_value_123")
    body = api.get(f"{BASE}/status").json()
    assert body["github_token_configured"] is True and "ghp_fake_secret_value_123" not in str(body)
    assert body["repository"] == "octo/demo"


def test_sync_then_list_runs(api):
    assert api.post(f"{BASE}/sync").json()["new"] == 3
    runs = api.get(f"{BASE}/runs").json()
    assert [r["run_id"] for r in runs] == [3001, 2002, 1001]
    assert runs[1]["conclusion"] == "failure" and runs[1]["analyzed"] is False
    assert "analysis" not in runs[1]


def test_analyze_failed_run_and_see_it_in_the_list(api):
    api.post(f"{BASE}/sync")
    response = api.post(f"{BASE}/runs/2002/analyze")
    assert response.status_code == 200
    assert response.json()["category"] == "test_failure"
    runs = {r["run_id"]: r for r in api.get(f"{BASE}/runs").json()}
    assert runs[2002]["analyzed"] is True and "is_low_stock" in runs[2002]["analysis_summary"]
    assert api.get(f"{BASE}/runs/2002").json()["analysis"]["confidence"] == "high"


def test_analyzing_a_successful_run_is_a_400(api):
    api.post(f"{BASE}/sync")
    assert api.post(f"{BASE}/runs/3001/analyze").status_code == 400


def test_unknown_run_and_unknown_repo_are_404(api):
    api.post(f"{BASE}/sync")
    assert api.post(f"{BASE}/runs/999/analyze").status_code == 404
    assert api.get(f"{BASE}/runs/999").status_code == 404
    assert api.get("/api/repos/nope__nope/pipeline/runs").status_code == 404


def test_github_errors_keep_their_status_and_message(api, monkeypatch):
    class Broken(FakeGitHub):
        def list_runs(self, *args, **kwargs):
            raise GitHubError("GitHub API rate limit reached. Set GITHUB_TOKEN", 429)

    monkeypatch.setattr(routes, "get_client", lambda: Broken())
    response = api.post(f"{BASE}/sync")
    assert response.status_code == 429 and "GITHUB_TOKEN" in response.json()["detail"]


def test_log_download_without_token_is_reported_clearly(api, monkeypatch):
    class NoLogs(FakeGitHub):
        def job_logs(self, *args, **kwargs):
            raise GitHubError("Downloading job logs needs a GitHub token. Set GITHUB_TOKEN", 401)

    monkeypatch.setattr(routes, "get_client", lambda: NoLogs())
    api.post(f"{BASE}/sync")
    response = api.post(f"{BASE}/runs/2002/analyze")
    assert response.status_code == 401 and "GITHUB_TOKEN" in response.json()["detail"]


def test_missing_llm_key_is_a_503(api, monkeypatch):
    def no_key():
        raise provider.LLMConfigError("OPENROUTER_API_KEY is not set")

    monkeypatch.setattr(provider, "get_llm", no_key)
    api.post(f"{BASE}/sync")
    response = api.post(f"{BASE}/runs/2002/analyze")
    assert response.status_code == 503 and "not set" in response.json()["detail"]


def test_llm_provider_failure_is_translated(api, monkeypatch):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    class Failing(FakeListChatModel):
        def _call(self, *args, **kwargs):
            raise RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")

    monkeypatch.setattr(provider, "get_llm", lambda: Failing(responses=["x"]))
    api.post(f"{BASE}/sync")
    response = api.post(f"{BASE}/runs/2002/analyze")
    assert response.status_code == 429 and "quota" in response.json()["detail"].lower()
