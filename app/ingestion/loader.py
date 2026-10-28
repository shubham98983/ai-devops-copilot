"""Walk a cloned repository and collect the files worth indexing."""
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build",
    ".idea", ".vscode", "site-packages", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    "htmlcov", ".tox", "coverage", "vendor", "target",
}
SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock",
}
SKIP_SUFFIXES = (".min.js", ".min.css", ".map", ".lock")

LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".js": "js", ".jsx": "js", ".ts": "ts", ".tsx": "ts",
    ".md": "markdown", ".rst": "text", ".txt": "text",
    ".json": "json", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml",
    ".ini": "text", ".cfg": "text", ".sql": "sql", ".sh": "shell",
    ".html": "html", ".css": "css",
}
LANGUAGE_BY_NAME = {"Dockerfile": "dockerfile", "Makefile": "make", ".env.example": "text"}

CODE_LANGUAGES = {"python", "js", "ts", "sql", "shell", "html", "css"}
DOC_LANGUAGES = {"markdown", "text"}


@dataclass
class SourceFile:
    path: str
    language: str
    kind: str
    text: str


def classify(path):
    """Return (language, kind) for a path, or None if the file should be skipped."""
    name = path.name
    if name in SKIP_FILES or name.endswith(SKIP_SUFFIXES):
        return None
    language = LANGUAGE_BY_NAME.get(name) or LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
    if language is None:
        return None
    if language in CODE_LANGUAGES:
        kind = "code"
    elif language in DOC_LANGUAGES:
        kind = "docs"
    else:
        kind = "config"
    return language, kind


def load_repo_files(root, max_files=500, max_bytes=200_000):
    """Return a list of SourceFile for every indexable file under root."""
    root = Path(root)
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts[:-1]):
            continue
        # hidden folders are skipped, except .github (workflows are valuable context)
        if any(part.startswith(".") and part != ".github" for part in relative.parts[:-1]):
            continue
        info = classify(path)
        if info is None:
            continue
        try:
            if path.stat().st_size > max_bytes:
                continue
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if not text.strip():
            continue
        language, kind = info
        files.append(SourceFile(relative.as_posix(), language, kind, text))
        if len(files) >= max_files:
            break
    return files
