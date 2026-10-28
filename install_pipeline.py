#!/usr/bin/env python3
"""Install the pipeline monitor (milestone 2) into an existing ai-devops-copilot project.

Run from the project root:   python install_pipeline.py

It only adds to your files and is safe to run twice. It never touches app/llm/provider.py
or app/config.py, so your own LLM settings (for example OpenRouter) stay as they are.
"""
import sys
from pathlib import Path

MARKER = "pipeline monitor (milestone 2)"

MAIN_BLOCK = f"""# --- {MARKER} ---
from app.pipeline.routes import router as pipeline_router  # noqa: E402

app.include_router(pipeline_router)

"""

TAB_BUTTON = '        <button class="tab" data-mode="pipeline">Pipeline</button>\n'
PANEL = f'      <!-- {MARKER} -->\n      <section id="pipeline-panel" class="panel" hidden></section>\n'
CSS_LINK = '  <link rel="stylesheet" href="pipeline.css">\n'
SCRIPT_TAG = '  <script src="pipeline.js"></script>\n'

ENV_BLOCK = """
# --- Pipeline monitor ---
# Token used to read GitHub Actions runs and logs. A fine-grained token with read access to
# Actions and Contents on your demo repository is enough. Never commit this file.
GITHUB_TOKEN=
# Seconds between automatic syncs (0 disables polling; the Sync button always works)
PIPELINE_POLL_SECONDS=60
"""


def patch_main(root, report):
    path = root / "app" / "main.py"
    text = path.read_text()
    if MARKER in text:
        report.append("app/main.py: already patched")
        return
    anchor = "if FRONTEND_DIR.exists():"
    if anchor not in text:
        raise SystemExit(
            "Could not find 'if FRONTEND_DIR.exists():' in app/main.py. Add these lines BEFORE the "
            "static files mount:\n\n" + MAIN_BLOCK
        )
    path.write_text(text.replace(anchor, MAIN_BLOCK + anchor, 1))
    report.append("app/main.py: pipeline router registered")


def patch_html(root, report):
    path = root / "frontend" / "index.html"
    text = path.read_text()
    if MARKER in text:
        report.append("frontend/index.html: already patched")
        return
    if 'data-mode="search"' not in text or "</main>" not in text:
        raise SystemExit("frontend/index.html has an unexpected layout; patch it by hand (see PIPELINE.md).")
    lines = text.splitlines(keepends=True)
    out = []
    for line in lines:
        out.append(line)
        if 'data-mode="search"' in line and "</button>" in line:
            out.append(TAB_BUTTON)
    text = "".join(out)
    text = text.replace("</main>", PANEL + "    </main>", 1)
    text = text.replace("</head>", CSS_LINK + "</head>", 1)
    text = text.replace("</body>", SCRIPT_TAG + "</body>", 1)
    path.write_text(text)
    report.append("frontend/index.html: Pipeline tab, panel, css and script added")


def patch_requirements(root, report):
    path = root / "requirements.txt"
    if not path.exists():
        return
    text = path.read_text()
    if "httpx" not in text:
        path.write_text(text.rstrip("\n") + "\nhttpx>=0.27\n")
        report.append("requirements.txt: added httpx (run: pip install httpx)")
    else:
        report.append("requirements.txt: httpx already listed")


def patch_env_example(root, report):
    path = root / ".env.example"
    if path.exists() and "GITHUB_TOKEN" not in path.read_text():
        path.write_text(path.read_text().rstrip("\n") + "\n" + ENV_BLOCK)
        report.append(".env.example: GITHUB_TOKEN section added")


def install(root):
    root = Path(root)
    if not (root / "app" / "main.py").exists() or not (root / "frontend" / "index.html").exists():
        raise SystemExit("Run this from the ai-devops-copilot project root (app/main.py not found).")
    report = []
    patch_main(root, report)
    patch_html(root, report)
    patch_requirements(root, report)
    patch_env_example(root, report)
    return report


if __name__ == "__main__":
    for line in install(Path.cwd()):
        print(" -", line)
    print("\nNext: pip install httpx, add GITHUB_TOKEN to .env, restart uvicorn.")
    if "--help" in sys.argv:
        print(__doc__)
