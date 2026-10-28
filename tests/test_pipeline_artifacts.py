import io
import json
import zipfile

import httpx
import pytest

from app.pipeline.github_client import GitHubClient, GitHubError


def test_zip_members_read_only_by_exact_name():
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w") as archive:
        archive.writestr("semgrep-report.json", '{"results":[]}')
        archive.writestr("nested/semgrep-report.json", "ignored")
        archive.writestr("unrelated.txt", "ignored")
    members = GitHubClient.read_artifact_members(memory.getvalue(), {"semgrep-report.json"})
    assert members == {"semgrep-report.json": b'{"results":[]}'}


def test_zip_limit_is_enforced():
    with pytest.raises(GitHubError, match="20 MB"):
        GitHubClient.read_artifact_members(b"x" * (20 * 1024 * 1024 + 1), set())


def test_download_uses_token_only_on_github_api_request():
    observed = []
    def handler(request):
        observed.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(200, content=b"zipdata")
    client = GitHubClient(token="secret-token", transport=httpx.MockTransport(handler))
    assert client.download_artifact("octo", "demo", 42) == b"zipdata"
    assert observed == [("https://api.github.com/repos/octo/demo/actions/artifacts/42/zip", "Bearer secret-token")]
    client._http.close()
