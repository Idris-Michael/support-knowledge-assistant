# 2. Keyword, vector and hybrid retrieval all built; the default chosen by measurement

Status: accepted

## Context
The design this ports used hybrid retrieval (full-text plus vectors, fused with Reciprocal Rank
Fusion) on the expectation that full-text search finds exact identifiers (`max_wal_size`, `40P01`)
and vectors find paraphrases. The PostgreSQL docs are full of identifiers, so hybrid looked like the
obvious default.

## Decision
Build all three behind one function (`retrieve.search`) and one LangChain retriever, and pick the
default from the gold question set, which was fixed before any retrieval code existed.

- **Keyword**: Postgres full-text search over the heading path and text. The question's stemmed words
  are OR-ed and ranked with `ts_rank` normalised by length. AND-ing them (`plainto_tsquery`) returned
  nothing for most ticket-length questions.
- **Vector**: pgvector cosine distance on nomic-embed-text, with its task prefixes
  (`search_document:` / `search_query:`). The heading path is embedded with each chunk, so
  "max_wal_size" carries "Write Ahead Log › Checkpoints" with it. `hnsw.iterative_scan = strict_order`
  keeps the access filter from starving the index scan.
- **Hybrid**: RRF (k = 60) over 30 candidates from each.
- One chunk per section: the best-ranked one.

## Result (50 answerable questions)
| Mode | hit@5 | MRR@10 |
|---|---|---|
| Keyword | 41/50 | 0.639 |
| Vector | **46/50** | **0.805** |
| Hybrid | 44/50 | 0.762 |

Vector is the default (`RETRIEVE_MODE=vector`). On identifier questions vector and hybrid tie
(19/20). Hybrid loses on paraphrased tickets: the OR-query adds loosely matching candidates and RRF
weighs them equally with the vector list. Two questions out of 50 is a small difference; the
ranking is reported, not presented as a general law.

The fusion weights and the keyword query were not tuned against this question set; doing so would
need a separate development set to avoid fitting the test.

## Consequences
- hit@5 counts a section as found even when it was split into chunks and the chunk kept is not the
  one with the answer. That happened twice in the end-to-end run (Q03, the error-code table, and
  Q42), and both showed up as refusals or gaps rather than wrong answers. Keeping the best two chunks
  per section, or splitting tables by row, is the next change to try.
- Keyword and hybrid stay available for clients whose documents are mostly codes and part numbers.
