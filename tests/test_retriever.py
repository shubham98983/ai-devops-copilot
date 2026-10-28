from app.ingestion.chunker import build_overview_document, chunk_files
from app.ingestion.loader import load_repo_files
from app.rag.retriever import extract_identifiers, hybrid_search, tokenize
from app.rag.vectorstore import rebuild_index


def index_sample(sample_repo, repo_id="octo__sample"):
    files = load_repo_files(sample_repo)
    documents = chunk_files(files, chunk_size=400, chunk_overlap=50)
    documents.append(build_overview_document(files, "octo/sample"))
    rebuild_index(repo_id, documents)
    return repo_id


def test_tokenize_splits_identifiers():
    tokens = tokenize("is_low_stock getUserName")
    assert {"is_low_stock", "low", "stock", "getusername", "user", "name"} <= set(tokens)


def test_exact_identifier_is_found_by_keyword_search(sample_repo):
    repo_id = index_sample(sample_repo)
    hits = hybrid_search(repo_id, "is_low_stock", k=5)
    assert hits[0]["metadata"]["path"] == "app/inventory.py"
    assert "bm25" in hits[0]["found_by"]


def test_language_filter(sample_repo):
    repo_id = index_sample(sample_repo)
    hits = hybrid_search(repo_id, "inventory JWT", k=5, language="markdown")
    assert hits and all(h["metadata"]["language"] == "markdown" for h in hits)


def test_kind_filter(sample_repo):
    repo_id = index_sample(sample_repo)
    hits = hybrid_search(repo_id, "login token", k=5, kind="code")
    assert hits and all(h["metadata"]["kind"] == "code" for h in hits)


def test_reindexing_replaces_old_chunks(sample_repo):
    repo_id = index_sample(sample_repo)
    (sample_repo / "app" / "inventory.py").write_text("def brand_new_function():\n    return 1\n")
    index_sample(sample_repo, repo_id)
    assert hybrid_search(repo_id, "brand_new_function", k=3)[0]["metadata"]["path"] == "app/inventory.py"
    assert all("is_low_stock" not in h["text"] for h in hybrid_search(repo_id, "is_low_stock", k=10))


def test_extract_identifiers():
    assert extract_identifiers("where is is_low_stock used?") == ["is_low_stock"]
    assert extract_identifiers("what does getUserName and SECRET_KEY do") == ["getUserName", "SECRET_KEY"]
    assert extract_identifiers("how does authentication work") == []


def test_chunks_containing_the_identifier_rank_first(sample_repo):
    repo_id = index_sample(sample_repo)
    hits = hybrid_search(repo_id, "what does SECRET_KEY do", k=5)
    assert "SECRET_KEY" in hits[0]["text"]
    assert "exact" in hits[0]["found_by"]
