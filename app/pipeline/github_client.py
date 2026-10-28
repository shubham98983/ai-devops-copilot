"""Minimal GitHub REST client for workflow runs, jobs and job logs.

The VM is behind NAT, so GitHub cannot call us. We poll this API instead.
"""
import os
import io
import zipfile

import httpx

API_ROOT = "https://api.github.com"
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024


class GitHubError(RuntimeError):
    """A GitHub API problem with a message the user can act on."""

    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code if 400 <= status_code <= 599 else 502


def get_token():
    return os.environ.get("GITHUB_TOKEN", "").strip()


def normalize_run(raw):
    commit = raw.get("head_commit") or {}
    message = (commit.get("message") or raw.get("display_title") or "").splitlines()
    return {
        "run_id": raw["id"],
        "run_number": raw.get("run_number"),
        "name": raw.get("name") or raw.get("display_title") or "workflow",
        "event": raw.get("event", ""),
        "branch": raw.get("head_branch") or "",
        "head_sha": raw.get("head_sha") or "",
        "message": message[0] if message else "",
        "status": raw.get("status") or "",
        "conclusion": raw.get("conclusion") or "",
        "html_url": raw.get("html_url") or "",
        "created_at": raw.get("created_at") or "",
        "updated_at": raw.get("updated_at") or "",
    }


def normalize_job(raw):
    steps = [
        {"name": step.get("name", ""), "conclusion": step.get("conclusion") or step.get("status") or ""}
        for step in raw.get("steps") or []
    ]
    return {
        "job_id": raw["id"],
        "name": raw.get("name", ""),
        "status": raw.get("status") or "",
        "conclusion": raw.get("conclusion") or "",
        "html_url": raw.get("html_url") or "",
        "failed_steps": [s["name"] for s in steps if s["conclusion"] == "failure"],
        "steps": steps,
    }


class GitHubClient:
    def __init__(self, token=None, transport=None, base_url=API_ROOT, timeout=20.0):
        self.token = get_token() if token is None else token
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-devops-copilot",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        # Log downloads redirect to another host; httpx drops the token on cross-origin redirects.
        self._http = httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
        )

    def _get(self, path, params=None):
        try:
            response = self._http.get(path, params=params)
        except httpx.HTTPError as error:
            raise GitHubError(f"Cannot reach GitHub: {error.__class__.__name__}", 502) from error
        self._raise_for_status(response)
        return response

    @staticmethod
    def _raise_for_status(response):
        status = response.status_code
        if status < 400:
            return
        if status in (403, 429) and response.headers.get("x-ratelimit-remaining") == "0":
            raise GitHubError(
                "GitHub API rate limit reached. Set GITHUB_TOKEN in .env (it raises the limit "
                "from 60 to 5000 requests per hour) and restart the server.",
                429,
            )
        if status == 401:
            raise GitHubError("GitHub rejected the token. Check GITHUB_TOKEN in .env.", 401)
        if status == 403:
            raise GitHubError(
                "GitHub denied access. The token needs read access to Actions on this repository.", 403
            )
        if status == 404:
            raise GitHubError(
                "Not found on GitHub. Check the repository name, that the token can see it, "
                "and that the logs have not expired (GitHub keeps them 90 days).",
                404,
            )
        raise GitHubError(f"GitHub returned HTTP {status}.", 502)

    def list_runs(self, owner, name, per_page=15, branch=None):
        params = {"per_page": per_page}
        if branch:
            params["branch"] = branch
        data = self._get(f"/repos/{owner}/{name}/actions/runs", params).json()
        return [normalize_run(raw) for raw in data.get("workflow_runs", [])]

    def list_jobs(self, owner, name, run_id):
        data = self._get(f"/repos/{owner}/{name}/actions/runs/{run_id}/jobs", {"per_page": 50}).json()
        return [normalize_job(raw) for raw in data.get("jobs", [])]

    def job_logs(self, owner, name, job_id):
        if not self.token:
            raise GitHubError(
                "Downloading job logs needs a GitHub token. Set GITHUB_TOKEN in .env and restart.", 401
            )
        return self._get(f"/repos/{owner}/{name}/actions/jobs/{job_id}/logs").text

    def list_artifacts(self, owner, name, run_id):
        data = self._get(f"/repos/{owner}/{name}/actions/runs/{run_id}/artifacts", {"per_page": 100}).json()
        return data.get("artifacts", [])

    def download_artifact(self, owner, name, artifact_id):
        """Download a small artifact ZIP without forwarding credentials off GitHub."""
        if not self.token:
            raise GitHubError("Downloading artifacts needs a GitHub token. Set GITHUB_TOKEN in .env and restart.", 401)
        url = f"/repos/{owner}/{name}/actions/artifacts/{artifact_id}/zip"
        try:
            with self._http.stream("GET", url, follow_redirects=False) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise GitHubError("GitHub returned an invalid artifact redirect.", 502)
                    # The signed storage URL is fetched by a client with no GitHub headers.
                    with httpx.Client(timeout=self._http.timeout, follow_redirects=True) as download:
                        with download.stream("GET", location) as redirected:
                            self._raise_for_status(redirected)
                            return self._read_bounded(redirected)
                self._raise_for_status(response)
                return self._read_bounded(response)
        except httpx.HTTPError as error:
            raise GitHubError(f"Cannot download artifact: {error.__class__.__name__}", 502) from error

    @staticmethod
    def _read_bounded(response):
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_ARTIFACT_BYTES:
                raise GitHubError("Artifact exceeds the 20 MB download limit.", 413)
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def read_artifact_members(blob, expected_names):
        """Return only named files from an in-memory zip, rejecting oversized archives/members."""
        if len(blob) > MAX_ARTIFACT_BYTES:
            raise GitHubError("Artifact exceeds the 20 MB download limit.", 413)
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                expected = set(expected_names)
                found = {}
                for info in archive.infolist():
                    if info.filename in expected and not info.is_dir():
                        if info.file_size > MAX_ARTIFACT_BYTES:
                            raise GitHubError("Artifact member exceeds the 20 MB limit.", 413)
                        found[info.filename] = archive.read(info)
                return found
        except (zipfile.BadZipFile, OSError) as error:
            raise GitHubError("GitHub returned an invalid artifact ZIP.", 502) from error
