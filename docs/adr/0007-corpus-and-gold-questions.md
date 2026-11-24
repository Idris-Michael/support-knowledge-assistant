# 7. The PostgreSQL docs as the corpus, and a gold set fixed before the code

Status: accepted

## Context
A retrieval benchmark is only as honest as its questions. Questions written after seeing what the
system retrieves tend to match it. The documents also need to be public, licensed for
redistribution, and realistic for a support desk.

## Decision
- **Corpus**: 116 pages of the PostgreSQL 18 documentation (Server Administration plus the reference
  pages a hosting desk is asked about), split into 755 sections at their own anchors. Configuration
  parameters and command options become sections of their own, so a citation lands on
  `max_wal_size` rather than a 40-parameter page. Redistributed under the PostgreSQL Licence
  (`corpus/NOTICE`). Plus eight internal notes for a fictional managed-Postgres host (30 sections),
  four for support and four for SRE.
- **Gold set**: 64 questions written in ticket language, committed (ba3947e) before any retrieval
  code. 50 answerable, labelled with the sections that answer them; 8 with no answer in the corpus;
  6 asking for notes above the asker's level. Every label is checked to exist in CI.
- Labels are not changed after a run. Where a run disagreed with a label (Q60), the disagreement is
  reported.

## Consequences
- The questions were written by Claude from the corpus text, so they may share its vocabulary more
  than real tickets do; they were phrased as customers write, not as the docs do. A random ten are
  set aside for a person's review (`bench/spot_check.md`). Real tickets from a pilot would be a better set.
- `page#*` labels (any section of a page) are used for reference pages whose subsections have only
  generated ids. That makes those questions easier to hit than ones labelled with one section.
- The parser is tied to the docs' HTML structure. A manifest records each page's hash, so a rebuild
  can tell when postgresql.org has changed the text.
