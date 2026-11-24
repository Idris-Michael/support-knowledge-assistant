"""Retrieval benchmark: keyword vs vector vs hybrid on the fixed question set, plus the leak check.

    uv run python bench/retrieval.py            # writes bench/out/retrieval.json

hit@5   share of answerable questions with at least one gold section in the top five sections
MRR@10  mean of 1/rank of the first gold section in the top ten (0 if none)
Leak check: every question is run as every role in every mode; a returned chunk the role may not read,
or any SRE canary string in text returned to a non-SRE role, counts as a leak.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

from langchain_core.embeddings import Embeddings

from support_knowledge_assistant.config import ROLE_GROUPS, Settings
from support_knowledge_assistant.db import make_engine
from support_knowledge_assistant.embeddings import make_embeddings
from support_knowledge_assistant.retrieve import search

ROOT = Path(__file__).resolve().parent
MODES = ("keyword", "vector", "hybrid")
CANARY = "KESTREL-CANARY"


class CachedEmbeddings(Embeddings):
    """Embed each question once, so the three modes see identical query vectors."""

    def __init__(self, inner: Embeddings) -> None:
        self.inner = inner
        self.cache: dict[str, list[float]] = {}

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        if text not in self.cache:
            self.cache[text] = self.inner.embed_query(text)
        return self.cache[text]


def matches(section_id: str, gold: str) -> bool:
    return section_id.startswith(gold[:-1]) if gold.endswith("#*") else section_id == gold


def first_gold_rank(sections: list[str], gold: list[str]) -> int | None:
    for i, sid in enumerate(sections, 1):
        if any(matches(sid, g) for g in gold):
            return i
    return None


def main() -> int:
    settings = Settings()
    engine = make_engine(settings.database_url)
    emb = CachedEmbeddings(make_embeddings(settings))
    questions = [
        json.loads(ln) for ln in (ROOT / "questions.jsonl").read_text(encoding="utf-8").splitlines() if ln
    ]
    answerable = [q for q in questions if q["expect"] == "answer"]

    per_question: list[dict[str, object]] = []
    summary: dict[str, dict[str, object]] = {}
    for mode in MODES:
        ranks: list[int | None] = []
        by_cat: dict[str, list[bool]] = defaultdict(list)
        timings: list[float] = []
        for q in answerable:
            started = time.perf_counter()
            hits = search(
                engine,
                emb,
                q["question"],
                ROLE_GROUPS[q["role"]],
                mode=mode,
                k=10,
                candidates=settings.retrieve_candidates,
            )
            timings.append(time.perf_counter() - started)
            sections = [h.section_id for h in hits]
            rank = first_gold_rank(sections, q["gold"])
            ranks.append(rank)
            by_cat[q["category"]].append(rank is not None and rank <= 5)
            per_question.append({"id": q["id"], "mode": mode, "rank": rank, "top5": sections[:5]})
        hit5 = [r is not None and r <= 5 for r in ranks]
        summary[mode] = {
            "hit_at_5": round(sum(hit5) / len(hit5), 3),
            "hits": f"{sum(hit5)}/{len(hit5)}",
            "mrr_at_10": round(statistics.fmean(1 / r if r else 0 for r in ranks), 3),
            "by_category": {c: f"{sum(v)}/{len(v)}" for c, v in sorted(by_cat.items())},
            "median_ms": round(statistics.median(timings) * 1000, 1),
        }

    leaks: list[dict[str, object]] = []
    checks = 0
    for q in questions:
        for role, groups in ROLE_GROUPS.items():
            for mode in MODES:
                checks += 1
                for h in search(
                    engine,
                    emb,
                    q["question"],
                    groups,
                    mode=mode,
                    k=10,
                    candidates=settings.retrieve_candidates,
                ):
                    if not set(h.acl) & set(groups) or (role != "sre" and CANARY in h.text):
                        leaks.append(
                            {
                                "id": q["id"],
                                "role": role,
                                "mode": mode,
                                "section": h.section_id,
                            }
                        )

    result = {
        "measured": time.strftime("%Y-%m-%d"),
        "embed_model": settings.embed_model,
        "answerable_questions": len(answerable),
        "modes": summary,
        "leak_check": {"searches": checks, "leaks": len(leaks), "details": leaks},
        "per_question": per_question,
    }
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "retrieval.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for mode, s in summary.items():
        print(
            f"{mode:8} hit@5 {s['hits']:>6} ({s['hit_at_5']:.0%})  MRR@10 {s['mrr_at_10']:.3f}  "
            f"median {s['median_ms']} ms  {s['by_category']}"
        )
    print(f"leak check: {checks} searches, {len(leaks)} leaks")
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
