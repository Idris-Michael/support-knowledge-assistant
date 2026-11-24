"""Wires settings to a ready Assistant: the retriever (pgvector or a managed index) and the two models."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.engine import Engine

from .agent import Assistant
from .config import Settings
from .db import make_engine
from .embeddings import make_embeddings
from .llm import make_chat
from .retrieve import Hit, search

Retrieve = Callable[[str, list[str]], list[Hit]]


def make_retriever(settings: Settings, engine: Engine | None = None) -> Retrieve:
    if settings.retriever == "azure-search":
        from .adapters import AzureSearchRetriever

        if not settings.azure_search_endpoint or settings.azure_search_key is None:
            raise ValueError("RETRIEVER=azure-search needs AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY")
        return AzureSearchRetriever(
            settings.azure_search_endpoint,
            settings.azure_search_index,
            settings.azure_search_key.get_secret_value(),
            make_embeddings(settings),
            k=settings.retrieve_k,
        )
    if settings.retriever == "bedrock-kb":
        import boto3

        from .adapters import BedrockKBRetriever

        if not settings.bedrock_kb_id:
            raise ValueError("RETRIEVER=bedrock-kb needs BEDROCK_KB_ID")
        client = boto3.client("bedrock-agent-runtime", region_name=settings.aws_region)
        return BedrockKBRetriever(client, settings.bedrock_kb_id, k=settings.retrieve_k)

    db = engine or make_engine(settings.database_url)
    embeddings = make_embeddings(settings) if settings.retrieve_mode != "keyword" else None

    def retrieve(question: str, groups: list[str]) -> list[Hit]:
        return search(
            db,
            embeddings,
            question,
            groups,
            mode=settings.retrieve_mode,
            k=settings.retrieve_k,
            candidates=settings.retrieve_candidates,
        )

    return retrieve


def build_assistant(settings: Settings, engine: Engine | None = None) -> Assistant:
    return Assistant(
        make_retriever(settings, engine),
        make_chat(settings, settings.grade_model),
        make_chat(settings, settings.answer_model),
    )
