import json
from pathlib import Path

import httpx
import pytest

from app.pipeline.github_client import GitHubClient, GitHubError

FIXTURES = Path(__file__).parent / "fixtures"


def client_with(handler, token="tok"):
    return GitHubClient(token=token, transport=httpx.MockTransport(handler))


def test_list_runs_normalizes_the_github_payload():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=json.loads((FIXTURES / "github_runs.json").read_text()))

    runs = client_with(handler).list_runs("octo", "demo", per_page=5)
    assert "/repos/octo/demo/actions/runs" in seen["url"] and "per_page=5" in seen["url"]
    assert seen["auth"] == "Bearer tok"
    assert [r["run_id"] for r in runs] == [3001, 2002, 1001]
    assert runs[0]["message"] == "Fix low stock threshold comparison"  # first line only
    assert runs[2]["conclusion"] == "" and runs[2]["message"] == "Add CI workflow and Dockerfile"


def test_list_jobs_reports_failed_steps():
    payload = json.loads((FIXTURES / "github_jobs.json").read_text())
    handler = lambda request: httpx.Response(200, json=payload)  # noqa: E731
    jobs = client_with(handler).list_jobs("octo", "demo", 2002)
    assert jobs[0]["failed_steps"] == ["Lint (Ruff)", "Test (pytest + coverage)"]
    assert [j["conclusion"] for j in jobs] == ["failure", "success", "skipped"]


def test_job_logs_follow_redirect_without_leaking_the_token():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "api.github.com":
            return httpx.Response(302, headers={"location": "https://blob.example.net/log.txt?sig=abc"})
        return httpx.Response(200, text="log body")

    assert client_with(handler).job_logs("octo", "demo", 5001) == "log body"
    assert requests[0].headers["authorization"] == "Bearer tok"
    assert "authorization" not in requests[1].headers


def test_logs_need_a_token():
    client = GitHubClient(token="", transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(GitHubError, match="GITHUB_TOKEN"):
        client.job_logs("octo", "demo", 1)


@pytest.mark.parametrize(
    "status, headers, keyword, expected_status",
    [
        (403, {"x-ratelimit-remaining": "0"}, "rate limit", 429),
        (401, {}, "rejected the token", 401),
        (403, {}, "denied access", 403),
        (404, {}, "not found", 404),
        (500, {}, "http 500", 502),
    ],
)
def test_errors_have_actionable_messages(status, headers, keyword, expected_status):
    client = client_with(lambda request: httpx.Response(status, headers=headers, json={}))
    with pytest.raises(GitHubError) as excinfo:
        client.list_runs("octo", "demo")
    assert keyword in str(excinfo.value).lower()
    assert excinfo.value.status_code == expected_status


def test_network_failure_is_reported():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(GitHubError, match="Cannot reach GitHub"):
        client_with(handler).list_runs("octo", "demo")
