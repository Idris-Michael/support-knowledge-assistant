"""Embeddings. nomic-embed-text is trained with task prefixes; documents and queries embedded without
them land in a slightly different space, so the prefixes are added here, in one place."""

from __future__ import annotations

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


def make_embeddings(settings: Settings) -> Embeddings:
    return PrefixedEmbeddings(OllamaEmbeddings(model=settings.embed_model, base_url=settings.ollama_url))
