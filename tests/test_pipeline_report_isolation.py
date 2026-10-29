import io
import json
import zipfile

import httpx

from app.pipeline import routes, store, sync
from app.pipeline.github_client import GitHubClient
from tests.pipeline_helpers import REPO_ID, register_repo


def _artifact(run_id, artifact_id, title):
    data = {
        "results": [
            {
                "check_id": f"test.rule.{run_id}",
                "path": f"app/run_{run_id}.py",
                "start": {"line": run_id},
                "extra": {"severity": "ERROR", "message": title},
            }
        ]
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("semgrep-report.json", json.dumps(data))
    return buffer.getvalue()


class PerRunArtifactClient:
    def __init__(self):
        self.runs = [
            {"run_id": run_id, "run_number": run_id - 100, "name": "CI", "status": "completed"}
            for run_id in (101, 102, 103)
        ]
        self.artifact_calls = []
        self.blobs = {501: _artifact(101, 501, "finding belonging to run 101")}
        self.blobs[502] = _artifact(102, 502, "finding belonging to run 102")

    def list_runs(self, owner, name, per_page=15, branch=None):
        return self.runs

    def list_jobs(self, owner, name, run_id):
        return []

    def list_artifacts(self, owner, name, run_id):
        self.artifact_calls.append(run_id)
        artifact_id = {101: 501, 102: 502}.get(run_id)
        if artifact_id is None:
            return []
        return [{"id": artifact_id, "name": "security-reports", "expired": False}]

    def download_artifact(self, owner, name, artifact_id):
        return self.blobs[artifact_id]

    read_artifact_members = staticmethod(GitHubClient.read_artifact_members)


def test_run_artifacts_and_post_report_response_are_isolated(monkeypatch):
    register_repo()
    client = PerRunArtifactClient()
    monkeypatch.setattr(routes, "get_client", lambda: client)

    sync.sync_repo(REPO_ID, client=client)

    first = routes.get_reports(REPO_ID, 101)
    second = routes.get_reports(REPO_ID, 102)
    missing = routes.get_reports(REPO_ID, 103)

    assert client.artifact_calls == [101, 102, 103]
    assert [finding["title"] for finding in first["findings"]] == ["finding belonging to run 101"]
    assert [finding["title"] for finding in second["findings"]] == ["finding belonging to run 102"]
    assert missing["findings"] == []
    assert missing["security_report_reason"] == "No security report artifact found for this run."
    assert store.get_report(REPO_ID, 101)["reports"]["findings"] == first["findings"]
    assert store.get_report(REPO_ID, 102)["reports"]["findings"] == second["findings"]


def test_artifact_listing_url_is_scoped_to_the_requested_run():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"artifacts": []})

    client = GitHubClient(token="token", transport=httpx.MockTransport(handler))

    client.list_artifacts("octo", "demo", 102)

    assert requests[0].url.path == "/repos/octo/demo/actions/runs/102/artifacts"
