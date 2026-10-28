"""Embedding model factory (bge-small on CPU by default)."""
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from app.config import get_settings

BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class QueryPrefixEmbeddings(Embeddings):
    """bge models work best when search queries (not documents) get an instruction prefix."""

    def __init__(self, inner, prefix):
        self.inner = inner
        self.prefix = prefix

    def embed_documents(self, texts):
        return self.inner.embed_documents(texts)

    def embed_query(self, text):
        return self.inner.embed_query(self.prefix + text)


@lru_cache(maxsize=4)
def _build(provider, model):
    if provider == "fake":
        from langchain_core.embeddings import DeterministicFakeEmbedding

        return DeterministicFakeEmbedding(size=384)

    from langchain_huggingface import HuggingFaceEmbeddings

    inner = HuggingFaceEmbeddings(
        model_name=model,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    prefix = BGE_QUERY_INSTRUCTION if "bge" in model.lower() else ""
    return QueryPrefixEmbeddings(inner, prefix) if prefix else inner


def get_embeddings():
    settings = get_settings()
    return _build(settings.embedding_provider, settings.embedding_model)
