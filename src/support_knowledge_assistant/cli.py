"""Command line: build the corpus, index it, search it, ask it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import corpus

ROOT = Path.cwd()


def _corpus_fetch(args: argparse.Namespace) -> int:
    pages = corpus.read_page_list(Path(args.pages))
    manifest = corpus.fetch_pages(pages, Path(args.raw))
    Path(args.manifest).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    missing = [p["page"] for p in manifest["pages"] if p.get("status") != 200]  # type: ignore[attr-defined]
    print(f"{len(pages) - len(missing)} pages fetched; missing: {', '.join(missing) or 'none'}")
    return 0


def _corpus_build(args: argparse.Namespace) -> int:
    pages = corpus.read_page_list(Path(args.pages))
    sections = corpus.build_sections(pages, Path(args.raw), Path(args.internal))
    corpus.write_jsonl(sections, Path(args.out))
    internal = sum(1 for s in sections if s.source == "internal")
    print(f"{len(sections)} sections ({internal} internal) -> {args.out}")
    return 0


def _index(args: argparse.Namespace) -> int:
    from .config import Settings
    from .db import make_engine
    from .embeddings import make_embeddings
    from .indexer import index

    settings = Settings()
    sections = corpus.read_jsonl(Path(args.sections))
    stats = index(
        make_engine(settings.database_url),
        make_embeddings(settings),
        sections,
        model=settings.embed_model,
    )
    print(
        f"{stats.chunks} chunks from {len(sections)} sections: {stats.embedded} embedded, "
        f"{stats.reused} reused, {stats.removed} removed"
    )
    return 0


def _search(args: argparse.Namespace) -> int:
    from .config import ROLE_GROUPS, Settings
    from .db import make_engine
    from .embeddings import make_embeddings
    from .retrieve import search

    settings = Settings()
    hits = search(
        make_engine(settings.database_url),
        make_embeddings(settings) if args.mode != "keyword" else None,
        args.question,
        ROLE_GROUPS[args.role],
        mode=args.mode,
        k=args.k,
        candidates=settings.retrieve_candidates,
    )
    for i, h in enumerate(hits, 1):
        ranks = f"kw={h.keyword_rank or '-'} vec={h.vector_rank or '-'}"
        print(f"{i}. {h.section_id}  [{ranks}]  {h.heading}")
    return 0


def _ask(args: argparse.Namespace) -> int:
    from .config import Principal, Settings
    from .service import build_assistant

    result = build_assistant(Settings()).ask(args.question, Principal(name="cli", role=args.role))
    print(result.answer)
    for c in result.citations:
        print(f"  [{c.n}] {c.heading}  {c.url}")
    reason = f" ({result.reason})" if result.reason else ""
    print(f"-- {result.outcome}{reason}, {result.latency_ms} ms, graded relevant: {result.relevant}")
    return 0 if result.outcome != "error" else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ska", description="Support knowledge assistant")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("corpus", help="fetch and build the document set")
    csub = c.add_subparsers(dest="corpus_cmd", required=True)
    f = csub.add_parser("fetch", help="download the PostgreSQL docs pages")
    f.add_argument("--pages", default="corpus/pages.txt")
    f.add_argument("--raw", default="corpus/raw")
    f.add_argument("--manifest", default="corpus/manifest.json")
    f.set_defaults(fn=_corpus_fetch)
    b = csub.add_parser("build", help="split pages and internal notes into citable sections")
    b.add_argument("--pages", default="corpus/pages.txt")
    b.add_argument("--raw", default="corpus/raw")
    b.add_argument("--internal", default="corpus/internal")
    b.add_argument("--out", default="corpus/sections.jsonl")
    b.set_defaults(fn=_corpus_build)

    i = sub.add_parser("index", help="chunk, embed and store the sections")
    i.add_argument("--sections", default="corpus/sections.jsonl")
    i.set_defaults(fn=_index)

    s = sub.add_parser("search", help="show what retrieval returns for a question")
    s.add_argument("question")
    s.add_argument("--role", choices=["customer", "support", "sre"], default="customer")
    s.add_argument("--mode", choices=["keyword", "vector", "hybrid"], default="hybrid")
    s.add_argument("-k", type=int, default=5)
    s.set_defaults(fn=_search)

    a = sub.add_parser("ask", help="answer a question with citations, or refuse")
    a.add_argument("question")
    a.add_argument("--role", choices=["customer", "support", "sre"], default="customer")
    a.set_defaults(fn=_ask)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
