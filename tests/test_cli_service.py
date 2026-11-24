"""CLI commands, the embeddings wrapper, service wiring and telemetry set-up."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.embeddings import Embeddings
from sqlalchemy.engine import Engine

from support_knowledge_assistant import cli, corpus, telemetry
from support_knowledge_assistant.config import Principal, Settings
from support_knowledge_assistant.embeddings import HashEmbeddings, PrefixedEmbeddings, make_embeddings
from support_knowledge_assistant.indexer import index
from support_knowledge_assistant.service import build_assistant
from tests.test_corpus import PAGE
from tests.test_postgres import CORPUS, EMB


class Recorder(Embeddings):
    def __init__(self) -> None:
        self.docs: list[str] = []
        self.queries: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.docs.extend(texts)
        return [[1.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [1.0]


def test_nomic_task_prefixes_are_added() -> None:
    inner = Recorder()
    emb = PrefixedEmbeddings(inner)
    emb.embed_documents(["max_wal_size"])
    emb.embed_query("is it a hard limit")
    assert inner.docs == ["search_document: max_wal_size"]
    assert inner.queries == ["search_query: is it a hard limit"]
    assert isinstance(make_embeddings(Settings()), PrefixedEmbeddings)
    hashed = make_embeddings(Settings(embed_provider="hash"))
    assert isinstance(hashed, HashEmbeddings) and len(hashed.embed_query("a b")) == 768


def test_corpus_build_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "runtime-config-wal.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "internal").mkdir()
    pages = tmp_path / "pages.txt"
    pages.write_text("runtime-config-wal\n", encoding="utf-8")
    out = tmp_path / "s.jsonl"
    argv = [
        "corpus",
        "build",
        "--pages",
        str(pages),
        "--raw",
        str(raw),
        "--internal",
        str(tmp_path / "internal"),
    ]
    assert cli.main([*argv, "--out", str(out)]) == 0
    assert "3 sections (0 internal)" in capsys.readouterr().out
    assert len(corpus.read_jsonl(out)) == 3


def test_corpus_fetch_records_missing_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_fetch(pages: list[str], raw: Path) -> dict[str, object]:
        return {"pages": [{"page": "a", "status": 200}, {"page": "b", "status": 404}]}

    monkeypatch.setattr(corpus, "fetch_pages", fake_fetch)
    pages = tmp_path / "p.txt"
    pages.write_text("a\nb\n", encoding="utf-8")
    manifest = tmp_path / "m.json"
    assert (
        cli.main(
            ["corpus", "fetch", "--pages", str(pages), "--raw", str(tmp_path), "--manifest", str(manifest)]
        )
        == 0
    )
    assert "1 pages fetched; missing: b" in capsys.readouterr().out
    assert manifest.exists()


@pytest.mark.integration
def test_search_and_ask_commands(
    engine: Engine, pg_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    index(engine, EMB, CORPUS, model="fake")
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("LLM_MODE", "offline")
    monkeypatch.setenv("RETRIEVE_MODE", "keyword")
    assert cli.main(["search", "VACUUM FULL rewrites", "--mode", "keyword"]) == 0
    assert "1. vacuum#SPACE  [kw=1 vec=-]" in capsys.readouterr().out
    assert cli.main(["ask", "does VACUUM FULL rewrite the table"]) == 0
    out = capsys.readouterr().out
    assert "[1]" in out and "-- answered" in out


@pytest.mark.integration
def test_build_assistant_wires_role_and_mode(engine: Engine) -> None:
    index(engine, EMB, CORPUS, model="fake")
    a = build_assistant(Settings(llm_mode="offline", retrieve_mode="keyword"), engine)
    r = a.ask("break-glass superuser vault path", Principal(name="t", role="customer"))
    assert all(h.acl == ["public"] for h in r.retrieved)
    assert r.outcome == "refused"
    sre = a.ask("break-glass superuser vault path", Principal(name="t", role="sre"))
    assert sre.retrieved[0].section_id == "internal/breakglass#steps"


def test_telemetry_setup_without_endpoint_is_quiet() -> None:
    telemetry.setup("ska-test", None)
