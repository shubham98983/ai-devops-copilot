"""Validate GitHub URLs and clone or update repositories."""
import os
import re
from pathlib import Path

from git import Repo

GITHUB_URL = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


def parse_github_url(url):
    """Return (owner, name) for a public GitHub https URL, else raise ValueError.

    Only github.com https URLs are accepted so users cannot make the server clone
    arbitrary hosts or local paths.
    """
    match = GITHUB_URL.match((url or "").strip())
    if not match:
        raise ValueError("Enter a GitHub repository URL like https://github.com/owner/repo")
    return match.group("owner"), match.group("name")


def make_repo_id(owner, name):
    return f"{owner}__{name}"


def clone_or_pull(url, destination):
    """Shallow clone into destination, or refresh it if it already exists.

    Returns the commit SHA that is checked out.
    """
    destination = Path(destination)
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")  # never wait for credentials
    if (destination / ".git").exists():
        repo = Repo(destination)
        repo.git.fetch("--depth", "1", "origin")
        repo.git.reset("--hard", "FETCH_HEAD")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        repo = Repo.clone_from(url, destination, depth=1)
    return repo.head.commit.hexsha
