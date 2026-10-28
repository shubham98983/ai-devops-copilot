"""Runtime settings, read from environment variables on every call."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Read ROOT/.env into the environment. Variables already set in the shell win.
load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    llm_provider: str
    llm_model: str
    embedding_provider: str
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    max_files: int
    max_file_bytes: int
    top_k: int


def get_settings():
    return Settings(
        data_dir=Path(os.environ.get("DATA_DIR", ROOT / "data")),
        llm_provider=os.environ.get("LLM_PROVIDER", "gemini").lower().strip(),
        llm_model=os.environ.get("LLM_MODEL", "").strip(),
        embedding_provider=os.environ.get("EMBEDDING_PROVIDER", "huggingface").lower().strip(),
        embedding_model=os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        chunk_size=int(os.environ.get("CHUNK_SIZE", "1000")),
        chunk_overlap=int(os.environ.get("CHUNK_OVERLAP", "150")),
        max_files=int(os.environ.get("MAX_FILES", "500")),
        max_file_bytes=int(os.environ.get("MAX_FILE_BYTES", "200000")),
        top_k=int(os.environ.get("TOP_K", "6")),
    )
