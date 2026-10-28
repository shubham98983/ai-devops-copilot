"""Hybrid retrieval: vector similarity (Chroma) + BM25 keywords, merged with RRF."""
import re

from rank_bm25 import BM25Okapi

from app.rag.vectorstore import chunks_path, get_store, load_chunks

RRF_K = 60
EXACT_MATCH_BONUS = 0.05  # larger than any RRF score, so literal identifier matches rank first
IDENTIFIER_PATTERN = re.compile(
    r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b"  # snake_case and SCREAMING_SNAKE
    r"|\b[a-z]+[A-Z][A-Za-z0-9]*\b"  # camelCase
    r"|\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b"  # PascalCase
)
TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

_bm25_cache = {}


def tokenize(text):
    """Split text into lowercase tokens, keeping whole identifiers and their parts.

    'is_low_stock' -> is_low_stock, is, low, stock;  'getUserName' -> getusername, get, user, name
    """
    tokens = []
    for word in TOKEN_PATTERN.findall(text):
        tokens.append(word.lower())
        parts = [p for p in re.split(r"_+", word) for p in CAMEL_BOUNDARY.split(p) if p]
        if len(parts) > 1:
            tokens.extend(part.lower() for part in parts)
    return tokens


class BM25Index:
    def __init__(self, documents):
        self.documents = documents
        self.model = BM25Okapi([tokenize(d.page_content) for d in documents]) if documents else None

    def search(self, query, limit, language=None, kind=None):
        if self.model is None:
            return []
        scores = self.model.get_scores(tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        results = []
        for index in ranked:
            doc = self.documents[index]
            if scores[index] <= 0:
                break
            if not matches_filters(doc.metadata, language, kind):
                continue
            results.append(doc)
            if len(results) >= limit:
                break
        return results


def extract_identifiers(query):
    """Code identifiers mentioned in a query, e.g. 'where is is_low_stock used' -> ['is_low_stock']."""
    return list(dict.fromkeys(IDENTIFIER_PATTERN.findall(query)))


def matches_filters(metadata, language, kind):
    if language and metadata.get("language") != language:
        return False
    if kind and metadata.get("kind") != kind:
        return False
    return True


def get_bm25(repo_id):
    path = chunks_path(repo_id)
    if not path.exists():
        return BM25Index([])
    mtime = path.stat().st_mtime
    cached = _bm25_cache.get(repo_id)
    if cached and cached[0] == mtime:
        return cached[1]
    index = BM25Index(load_chunks(repo_id))
    _bm25_cache[repo_id] = (mtime, index)
    return index


def build_where(language, kind):
    conditions = []
    if language:
        conditions.append({"language": language})
    if kind:
        conditions.append({"kind": kind})
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


def hybrid_search(repo_id, query, k=6, language=None, kind=None):
    """Return up to k chunks as dicts with text, metadata, score and which retrievers found them."""
    fetch = max(k * 3, 12)
    vector_docs = get_store(repo_id).similarity_search(
        query, k=fetch, filter=build_where(language, kind)
    )
    keyword_docs = get_bm25(repo_id).search(query, fetch, language, kind)

    fused = {}
    for source, docs in (("vector", vector_docs), ("bm25", keyword_docs)):
        for rank, doc in enumerate(docs):
            key = doc.metadata["chunk_id"]
            entry = fused.setdefault(key, {"doc": doc, "score": 0.0, "found_by": []})
            entry["score"] += 1.0 / (RRF_K + rank + 1)
            entry["found_by"].append(source)

    for identifier in extract_identifiers(query):
        for entry in fused.values():
            if identifier in entry["doc"].page_content:
                entry["score"] += EXACT_MATCH_BONUS
                if "exact" not in entry["found_by"]:
                    entry["found_by"].append("exact")

    ranked = sorted(fused.values(), key=lambda e: e["score"], reverse=True)[:k]
    return [
        {
            "text": entry["doc"].page_content,
            "metadata": entry["doc"].metadata,
            "score": round(entry["score"], 5),
            "found_by": entry["found_by"],
        }
        for entry in ranked
    ]
