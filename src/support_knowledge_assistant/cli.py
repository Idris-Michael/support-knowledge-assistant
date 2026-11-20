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
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
