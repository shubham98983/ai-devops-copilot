"""FastAPI application: repository indexing, Q&A chat, semantic search and the web UI."""
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import indexer, store
from app.config import get_settings
from app.ingestion import cloner
from app.llm.provider import LLMConfigError, key_configured
from app.rag import chain
from app.rag.retriever import hybrid_search
from app.utils import get_logger

log = get_logger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="AI DevOps Copilot", version="0.1.0")


class RepoRequest(BaseModel):
    url: str = Field(..., max_length=200)


class ChatTurn(BaseModel):
    role: str
    content: str = Field(..., max_length=4000)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    history: list[ChatTurn] = []


def get_ready_repo(repo_id):
    repo = store.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found. Index it first.")
    if repo["status"] != "ready":
        raise HTTPException(
            status_code=409, detail=f"Repository is not ready yet (status: {repo['status']})"
        )
    return repo


@app.get("/health")
def health():
    settings = get_settings()
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "embedding_model": settings.embedding_model,
        "llm_key_configured": key_configured(),
    }


@app.post("/api/repos", status_code=202)
def add_repo(request: RepoRequest, background_tasks: BackgroundTasks):
    try:
        owner, name = cloner.parse_github_url(request.url)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    repo_id = cloner.make_repo_id(owner, name)
    existing = store.get_repo(repo_id)
    if existing and existing["status"] in store.ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="This repository is already being indexed")

    clean_url = f"https://github.com/{owner}/{name}"
    store.upsert_repo(repo_id, clean_url, owner, name, status="queued")
    background_tasks.add_task(indexer.run_index, repo_id, clean_url)
    return store.get_repo(repo_id)


@app.get("/api/repos")
def list_repos():
    return store.list_repos()


@app.get("/api/repos/{repo_id}")
def get_repo(repo_id: str):
    repo = store.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@app.post("/api/repos/{repo_id}/chat")
def chat(repo_id: str, request: ChatRequest):
    get_ready_repo(repo_id)
    history = [turn.model_dump() for turn in request.history]
    try:
        return chain.answer_question(repo_id, request.question, history)
    except LLMConfigError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001
        log.exception("Chat failed for %s", repo_id)
        raise HTTPException(
            status_code=502, detail="The language model request failed. Check the server log."
        ) from error


@app.get("/api/repos/{repo_id}/search")
def search(
    repo_id: str,
    q: str = Query(..., min_length=2, max_length=300),
    k: int = Query(6, ge=1, le=20),
    language: Optional[str] = None,
    kind: Optional[str] = None,
):
    get_ready_repo(repo_id)
    hits = hybrid_search(repo_id, q, k=k, language=language, kind=kind)
    return [
        {
            "label": chain.source_label(hit["metadata"]),
            "path": hit["metadata"]["path"],
            "start_line": hit["metadata"]["start_line"],
            "end_line": hit["metadata"]["end_line"],
            "language": hit["metadata"]["language"],
            "symbols": hit["metadata"].get("symbols", ""),
            "found_by": hit["found_by"],
            "score": hit["score"],
            "snippet": chain.redact_secrets(chain.strip_header(hit["text"]))[:1200],
        }
        for hit in hits
    ]


# --- pipeline monitor (milestone 2) ---
from app.pipeline.routes import router as pipeline_router  # noqa: E402

app.include_router(pipeline_router)

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
