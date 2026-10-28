import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_env_file_is_loaded_without_shell_exports(tmp_path):
    """Regression: the app must read ROOT/.env itself (uvicorn does not)."""
    env_file = ROOT / ".env"
    if env_file.exists():
        pytest.skip("a real .env exists; this test only runs without one")
    env_file.write_text("LLM_PROVIDER=groq\nGROQ_API_KEY=from-dotenv-file\n")
    try:
        clean_env = {k: v for k, v in os.environ.items() if k not in ("LLM_PROVIDER", "GROQ_API_KEY")}
        code = (
            "from app.config import get_settings; from app.llm.provider import key_configured;"
            "print(get_settings().llm_provider, key_configured())"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, env=clean_env, capture_output=True, text=True
        )
        assert result.stdout.strip() == "groq True", result.stderr
    finally:
        env_file.unlink()
