import pytest

from app.ingestion.cloner import make_repo_id, parse_github_url


def test_valid_urls():
    assert parse_github_url("https://github.com/octo/hello-world") == ("octo", "hello-world")
    assert parse_github_url("https://github.com/octo/hello.git") == ("octo", "hello")
    assert parse_github_url("  https://github.com/octo/hello/  ") == ("octo", "hello")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "http://github.com/octo/hello",
        "https://gitlab.com/octo/hello",
        "https://github.com/octo",
        "https://github.com/octo/hello/tree/main",
        "file:///etc/passwd",
        "/tmp/local/repo",
        "https://github.com/octo/hello; rm -rf /",
        "git@github.com:octo/hello.git",
    ],
)
def test_invalid_urls_are_rejected(url):
    with pytest.raises(ValueError):
        parse_github_url(url)


def test_repo_id():
    assert make_repo_id("octo", "hello") == "octo__hello"
