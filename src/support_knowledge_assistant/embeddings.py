"""Embeddings. nomic-embed-text is trained with task prefixes; documents and queries embedded without
them land in a slightly different space, so the prefixes are added here, in one place.

`HashEmbeddings` is for CI and smoke tests only: word hashes, no meaning. It lets the whole stack run
where there is no Ollama, and its vector results are not a measure of anything."""

from __future__ import annotations

import hashlib

from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings

from .config import Settings


class PrefixedEmbeddings(Embeddings):
    def __init__(
        self,
        inner: Embeddings,
        doc_prefix: str = "search_document: ",
        query_prefix: str = "search_query: ",
    ) -> None:
        self.inner = inner
        self.doc_prefix = doc_prefix
        self.query_prefix = query_prefix

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed_documents([self.doc_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed_query(self.query_prefix + text)


class HashEmbeddings(Embeddings):
    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in text.lower().split():
            v[int(hashlib.sha256(word.encode()).hexdigest(), 16) % self.dim] += 1.0
        v[0] += 1e-3  # never the zero vector: cosine distance would be undefined
        return v

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def make_embeddings(settings: Settings) -> Embeddings:
    if settings.embed_provider == "hash":
        return HashEmbeddings(settings.embed_dim)
    return PrefixedEmbeddings(OllamaEmbeddings(model=settings.embed_model, base_url=settings.ollama_url))
