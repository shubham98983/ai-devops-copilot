import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("install_pipeline", ROOT / "install_pipeline.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

MAIN = '''from fastapi import FastAPI
app = FastAPI()


@app.get("/health")
def health():
    return {}


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
'''

HTML = """<html><head><title>x</title>
</head>
<body>
  <main class="main">
      <nav class="tabs">
        <button class="tab active" data-mode="chat">Ask the repo</button>
        <button class="tab" data-mode="search">Semantic search</button>
      </nav>
  </main>
  <script src="app.js"></script>
</body></html>
"""


@pytest.fixture
def project(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "app" / "main.py").write_text(MAIN)
    (tmp_path / "frontend" / "index.html").write_text(HTML)
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    (tmp_path / ".env.example").write_text("LLM_PROVIDER=gemini\n")
    return tmp_path


def test_installer_patches_every_file(project):
    installer.install(project)
    main = (project / "app" / "main.py").read_text()
    assert main.index("include_router(pipeline_router)") < main.index("if FRONTEND_DIR.exists():")
    html = (project / "frontend" / "index.html").read_text()
    assert 'data-mode="pipeline"' in html and 'id="pipeline-panel"' in html
    assert html.index("pipeline.css") < html.index("</head>")
    assert html.index("app.js") < html.index("pipeline.js") < html.index("</body>")
    assert "httpx" in (project / "requirements.txt").read_text()
    assert "GITHUB_TOKEN" in (project / ".env.example").read_text()


def test_installer_is_idempotent(project):
    installer.install(project)
    snapshot = {p.name: p.read_text() for p in project.rglob("*") if p.is_file()}
    report = installer.install(project)
    assert {p.name: p.read_text() for p in project.rglob("*") if p.is_file()} == snapshot
    assert any("already patched" in line for line in report)


def test_installer_refuses_to_run_in_the_wrong_folder(tmp_path):
    with pytest.raises(SystemExit):
        installer.install(tmp_path)


def test_installer_explains_what_to_do_when_main_py_was_changed(project):
    (project / "app" / "main.py").write_text("app = None\n")
    with pytest.raises(SystemExit, match="BEFORE the static files mount"):
        installer.install(project)
