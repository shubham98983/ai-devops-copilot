"""ChromaDB persistence: one collection per indexed repository."""
import hashlib
import json
import re
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import get_settings
from app.rag.embeddings import get_embeddings

BATCH_SIZE = 64


def collection_name(repo_id):
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", repo_id)
    if len(safe) > 50:
        safe = safe[:40] + "_" + hashlib.sha1(repo_id.encode()).hexdigest()[:8]
    return f"repo_{safe}"


def chroma_dir():
    return get_settings().data_dir / "chroma"


def chunks_path(repo_id):
    return get_settings().data_dir / "chunks" / f"{repo_id}.json"


def get_store(repo_id):
    chroma_dir().mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=collection_name(repo_id),
        embedding_function=get_embeddings(),
        persist_directory=str(chroma_dir()),
        collection_metadata={"hnsw:space": "cosine"},
    )


def save_chunks(repo_id, documents):
    """Persist raw chunks so the BM25 index can be rebuilt without re-embedding."""
    path = chunks_path(repo_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"text": d.page_content, "metadata": d.metadata} for d in documents]
    path.write_text(json.dumps(payload), encoding="utf-8")


def load_chunks(repo_id):
    path = chunks_path(repo_id)
    if not path.exists():
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Document(page_content=item["text"], metadata=item["metadata"]) for item in payload]


def rebuild_index(repo_id, documents):
    """Replace everything stored for this repo with the given documents."""
    store = get_store(repo_id)
    store.delete_collection()
    store = get_store(repo_id)
    for start in range(0, len(documents), BATCH_SIZE):
        batch = documents[start : start + BATCH_SIZE]
        store.add_documents(batch, ids=[d.metadata["chunk_id"] for d in batch])
    save_chunks(repo_id, documents)
    return len(documents)
