"""Managed-search retrievers with the same contract as `retrieve.search`: (question, groups) → hits,
access-filtered by the search service itself, one hit per section.

- `AzureSearchRetriever`: Azure AI Search hybrid query (text + vector, fused by the service with RRF),
  security-trimmed with an OData filter on a `acl` collection field.
- `BedrockKBRetriever`: Amazon Bedrock Knowledge Bases `Retrieve` with HYBRID search, filtered on an
  `acl` list metadata attribute.

Tested with mocks only (recorded response shapes); neither has run against a live service. The
index or knowledge base must carry the same fields the corpus sections have (see ADR 6).
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from langchain_core.embeddings import Embeddings

from .retrieve import Hit

GROUP = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
AZURE_API_VERSION = "2024-07-01"


class AccessFilterError(RuntimeError):
    pass


def _checked_groups(groups: list[str]) -> list[str]:
    # Groups come from server config, never the request; still, nothing odd goes into a filter string.
    bad = [g for g in groups if not GROUP.match(g)]
    if bad or not groups:
        raise ValueError(f"invalid access groups: {bad or groups}")
    return groups


def _dedupe(hits: list[Hit], groups: list[str], k: int) -> list[Hit]:
    out: list[Hit] = []
    seen: set[str] = set()
    for h in hits:
        if not set(h.acl) & set(groups):
            raise AccessFilterError(f"search service returned {h.section_id} outside {groups}")
        if h.section_id not in seen:
            seen.add(h.section_id)
            out.append(h)
        if len(out) >= k:
            break
    return out


class AzureSearchRetriever:
    def __init__(
        self,
        endpoint: str,
        index: str,
        api_key: str,
        embeddings: Embeddings,
        *,
        k: int = 5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = f"{endpoint.rstrip('/')}/indexes/{index}/docs/search?api-version={AZURE_API_VERSION}"
        self.embeddings = embeddings
        self.k = k
        self.http = httpx.Client(transport=transport, timeout=30, headers={"api-key": api_key})

    @staticmethod
    def acl_filter(groups: list[str]) -> str:
        return f"acl/any(g: search.in(g, '{','.join(_checked_groups(groups))}', ','))"

    def __call__(self, question: str, groups: list[str]) -> list[Hit]:
        body = {
            "search": question,
            "vectorQueries": [
                {
                    "kind": "vector",
                    "vector": self.embeddings.embed_query(question),
                    "fields": "embedding",
                    "k": self.k * 4,
                }
            ],
            "filter": self.acl_filter(groups),
            "top": self.k * 4,
            "select": "chunk_id,section_id,url,title,heading,text,acl,source",
        }
        res = self.http.post(self.url, json=body)
        if res.status_code != 200:
            raise RuntimeError(f"Azure AI Search {res.status_code}: {res.text[:200]}")
        hits = [
            Hit(
                chunk_id=int(doc.get("chunk_id", i)),
                section_id=doc["section_id"],
                url=doc["url"],
                title=doc.get("title", ""),
                heading=doc.get("heading", ""),
                text=doc["text"],
                acl=list(doc["acl"]),
                source=doc.get("source", ""),
                score=float(doc.get("@search.score", 0.0)),
            )
            for i, doc in enumerate(res.json().get("value", []))
        ]
        return _dedupe(hits, groups, self.k)


class BedrockKBRetriever:
    def __init__(self, client: Any, knowledge_base_id: str, *, k: int = 5) -> None:
        self.client = client  # boto3.client("bedrock-agent-runtime")
        self.kb = knowledge_base_id
        self.k = k

    @staticmethod
    def acl_filter(groups: list[str]) -> dict[str, Any]:
        clauses = [{"listContains": {"key": "acl", "value": g}} for g in _checked_groups(groups)]
        return clauses[0] if len(clauses) == 1 else {"orAll": clauses}

    def __call__(self, question: str, groups: list[str]) -> list[Hit]:
        res = self.client.retrieve(
            knowledgeBaseId=self.kb,
            retrievalQuery={"text": question},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": self.k * 4,
                    "overrideSearchType": "HYBRID",
                    "filter": self.acl_filter(groups),
                }
            },
        )
        hits = []
        for i, r in enumerate(res.get("retrievalResults", [])):
            meta = r.get("metadata", {})
            hits.append(
                Hit(
                    chunk_id=i,
                    section_id=str(meta["section_id"]),
                    url=str(meta.get("url", "")),
                    title=str(meta.get("title", "")),
                    heading=str(meta.get("heading", "")),
                    text=r["content"]["text"],
                    acl=[str(a) for a in meta.get("acl", [])],
                    source=str(meta.get("source", "")),
                    score=float(r.get("score", 0.0)),
                )
            )
        return _dedupe(hits, groups, self.k)
