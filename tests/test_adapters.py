"""Managed-search adapters against mocked services: request shape, access filter, parsing, and the
check that refuses a result outside the caller's groups."""

from __future__ import annotations

import json

import boto3
import httpx
import pytest
from botocore.stub import ANY, Stubber

from support_knowledge_assistant.adapters import AccessFilterError, AzureSearchRetriever, BedrockKBRetriever
from support_knowledge_assistant.embeddings import HashEmbeddings


def azure_doc(section: str, acl: list[str], score: float, chunk: int) -> dict[str, object]:
    return {
        "@search.score": score,
        "chunk_id": chunk,
        "section_id": section,
        "url": f"https://docs/{section}",
        "title": "T",
        "heading": f"T › {section}",
        "text": f"text of {section}",
        "acl": acl,
        "source": "docs",
    }


def test_azure_hybrid_query_with_security_filter() -> None:
    sent: list[dict[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["api-key"] == "k" * 32
        assert str(req.url) == "https://search.example/indexes/kb/docs/search?api-version=2024-07-01"
        sent.append(json.loads(req.content))
        docs = [
            azure_doc("vac#A", ["public"], 0.9, 1),
            azure_doc("vac#A", ["public"], 0.8, 2),
            azure_doc("wal#B", ["public", "support"], 0.7, 3),
        ]
        return httpx.Response(200, json={"value": docs})

    r = AzureSearchRetriever(
        "https://search.example/",
        "kb",
        "k" * 32,
        HashEmbeddings(),
        k=5,
        transport=httpx.MockTransport(handler),
    )
    hits = r("does vacuum shrink tables", ["public", "support"])
    assert [h.section_id for h in hits] == ["vac#A", "wal#B"]  # one per section, service order kept
    body = sent[0]
    assert body["filter"] == "acl/any(g: search.in(g, 'public,support', ','))"
    assert body["search"] == "does vacuum shrink tables"
    vq = body["vectorQueries"][0]  # type: ignore[index]
    assert vq["fields"] == "embedding" and len(vq["vector"]) == 768


def test_azure_result_outside_groups_is_refused() -> None:
    t = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"value": [azure_doc("sre#X", ["sre"], 1.0, 1)]})
    )
    r = AzureSearchRetriever("https://s", "kb", "k" * 32, HashEmbeddings(), transport=t)
    with pytest.raises(AccessFilterError, match="sre#X"):
        r("break glass", ["public"])


def test_azure_errors_surface() -> None:
    t = httpx.MockTransport(lambda req: httpx.Response(403, text="forbidden"))
    with pytest.raises(RuntimeError, match="403"):
        AzureSearchRetriever("https://s", "kb", "k" * 32, HashEmbeddings(), transport=t)("q", ["public"])


@pytest.mark.parametrize("groups", [[], ["public'), true or ('x"], ["Public"]])
def test_groups_are_validated_before_building_filters(groups: list[str]) -> None:
    with pytest.raises(ValueError, match="invalid access groups"):
        AzureSearchRetriever.acl_filter(groups)
    with pytest.raises(ValueError, match="invalid access groups"):
        BedrockKBRetriever.acl_filter(groups)


def bedrock_result(section: str, acl: list[str], score: float) -> dict[str, object]:
    return {
        "content": {"text": f"text of {section}"},
        "score": score,
        "location": {"type": "S3", "s3Location": {"uri": f"s3://kb/{section}"}},
        "metadata": {"section_id": section, "url": f"https://docs/{section}", "heading": section, "acl": acl},
    }


def stubbed(results: list[dict[str, object]], expected_filter: object) -> tuple[BedrockKBRetriever, Stubber]:
    client = boto3.client(
        "bedrock-agent-runtime", region_name="eu-west-2", aws_access_key_id="x", aws_secret_access_key="x"
    )
    stub = Stubber(client)
    stub.add_response(
        "retrieve",
        {"retrievalResults": results},
        {
            "knowledgeBaseId": "KB12345678",
            "retrievalQuery": {"text": ANY},
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {
                    "numberOfResults": 20,
                    "overrideSearchType": "HYBRID",
                    "filter": expected_filter,
                }
            },
        },
    )
    stub.activate()
    return BedrockKBRetriever(client, "KB12345678", k=5), stub


def test_bedrock_hybrid_retrieve_with_list_filter() -> None:
    expected = {
        "orAll": [
            {"listContains": {"key": "acl", "value": "public"}},
            {"listContains": {"key": "acl", "value": "support"}},
        ]
    }
    r, stub = stubbed(
        [bedrock_result("vac#A", ["public"], 0.9), bedrock_result("plans#B", ["support", "sre"], 0.5)],
        expected,
    )
    hits = r("connection limit", ["public", "support"])
    stub.assert_no_pending_responses()
    assert [(h.section_id, h.acl) for h in hits] == [("vac#A", ["public"]), ("plans#B", ["support", "sre"])]


def test_bedrock_single_group_filter_and_breach_detection() -> None:
    r, _ = stubbed(
        [bedrock_result("sre#X", ["sre"], 0.9)], {"listContains": {"key": "acl", "value": "public"}}
    )
    with pytest.raises(AccessFilterError):
        r("break glass", ["public"])


def test_service_picks_the_configured_retriever(monkeypatch: pytest.MonkeyPatch) -> None:
    from support_knowledge_assistant.config import Settings
    from support_knowledge_assistant.service import make_retriever

    az = make_retriever(
        Settings(retriever="azure-search", azure_search_endpoint="https://s", azure_search_key="k" * 32)
    )  # type: ignore[arg-type]
    assert isinstance(az, AzureSearchRetriever)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    assert isinstance(
        make_retriever(Settings(retriever="bedrock-kb", bedrock_kb_id="KB12345678")), BedrockKBRetriever
    )
    with pytest.raises(ValueError, match="AZURE_SEARCH_ENDPOINT"):
        make_retriever(Settings(retriever="azure-search"))
    with pytest.raises(ValueError, match="BEDROCK_KB_ID"):
        make_retriever(Settings(retriever="bedrock-kb"))
