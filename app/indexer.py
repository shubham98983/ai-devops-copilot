"""Clone -> load -> chunk -> embed -> store. Runs in a background task."""
from app import store
from app.config import get_settings
from app.ingestion import cloner
from app.ingestion.chunker import build_overview_document, chunk_files
from app.ingestion.loader import load_repo_files
from app.rag.vectorstore import rebuild_index
from app.utils import get_logger

log = get_logger(__name__)


def clone_path(repo_id):
    return get_settings().data_dir / "repos" / repo_id


def run_index(repo_id, url):
    """Index a repository, recording progress and any failure in the registry."""
    settings = get_settings()
    try:
        store.update_repo(repo_id, status="cloning")
        commit_sha = cloner.clone_or_pull(url, clone_path(repo_id))

        store.update_repo(repo_id, status="indexing", commit_sha=commit_sha)
        files = load_repo_files(clone_path(repo_id), settings.max_files, settings.max_file_bytes)
        if not files:
            raise ValueError("No indexable source files were found in this repository")

        documents = chunk_files(files, settings.chunk_size, settings.chunk_overlap)
        documents.append(build_overview_document(files, repo_id.replace("__", "/")))
        chunk_count = rebuild_index(repo_id, documents)

        store.update_repo(repo_id, status="ready", files=len(files), chunks=chunk_count)
        log.info("Indexed %s: %d files, %d chunks", repo_id, len(files), chunk_count)
    except Exception as error:  # noqa: BLE001 - surface any failure to the UI
        log.exception("Indexing failed for %s", repo_id)
        store.update_repo(repo_id, status="failed", error=str(error)[:300])
