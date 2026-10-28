from pathlib import Path

from app.ingestion.loader import classify, load_repo_files


def test_loader_skips_junk_and_binaries(sample_repo):
    paths = {f.path for f in load_repo_files(sample_repo)}
    assert paths == {"app/auth.py", "app/inventory.py", "config.py", "README.md"}


def test_loader_assigns_language_and_kind(sample_repo):
    by_path = {f.path: f for f in load_repo_files(sample_repo)}
    assert by_path["app/auth.py"].language == "python"
    assert by_path["app/auth.py"].kind == "code"
    assert by_path["README.md"].kind == "docs"


def test_loader_respects_file_limit(sample_repo):
    assert len(load_repo_files(sample_repo, max_files=2)) == 2


def test_loader_skips_large_files(sample_repo):
    (sample_repo / "big.py").write_text("x = 1\n" * 100_000)
    paths = {f.path for f in load_repo_files(sample_repo, max_bytes=1000)}
    assert "big.py" not in paths


def test_classify_known_and_unknown():
    assert classify(Path("a.py")) == ("python", "code")
    assert classify(Path("Dockerfile")) == ("dockerfile", "config")
    assert classify(Path("a.exe")) is None
    assert classify(Path("yarn.lock")) is None
