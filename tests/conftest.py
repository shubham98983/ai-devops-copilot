import pytest

from app.rag import embeddings, retriever


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Every test gets its own data directory and fake (offline) embeddings."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    embeddings._build.cache_clear()
    retriever._bm25_cache.clear()
    yield


@pytest.fixture
def sample_repo(tmp_path):
    """A small fake repository on disk, including files that must be skipped."""
    root = tmp_path / "sample"
    (root / "app").mkdir(parents=True)
    (root / "node_modules" / "junk").mkdir(parents=True)

    (root / "app" / "auth.py").write_text(
        'import jwt\n\n\ndef login(username, password):\n'
        '    """Check credentials and return a JWT token."""\n'
        "    user = find_user(username)\n    if user and user.check(password):\n"
        "        return jwt.encode({'sub': user.id}, SECRET)\n    return None\n\n\n"
        "def verify_token(token):\n    return jwt.decode(token, SECRET)\n"
    )
    (root / "app" / "inventory.py").write_text(
        "def is_low_stock(product):\n    return product.quantity < product.reorder_level\n\n\n"
        "def adjust_stock(product, delta):\n    product.quantity += delta\n    return product.quantity\n"
    )
    (root / "config.py").write_text('SECRET_KEY = "hunter2hunter2"\nDEBUG = True\n')
    (root / "README.md").write_text("# Sample\n\nA small inventory service with JWT login.\n")
    (root / "node_modules" / "junk" / "index.js").write_text("module.exports = 1;\n")
    (root / "package-lock.json").write_text("{}\n")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x00\x00")
    return root
