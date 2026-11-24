# 6. Adapters for Azure AI Search and Bedrock Knowledge Bases, tested with mocks

Status: accepted

## Context
Clients that already run Azure AI Search or Amazon Bedrock Knowledge Bases will not want a second
index in Postgres. The assistant should work against theirs without changing the graph.

## Decision
`adapters.py` implements the same contract as `retrieve.search`: `(question, groups) → hits`, one
per section.

- **Azure AI Search**: one hybrid request (text plus a vector query; the service fuses them with RRF),
  security-trimmed with `acl/any(g: search.in(g, 'public,support', ','))`.
- **Bedrock Knowledge Bases**: `Retrieve` with `overrideSearchType = HYBRID`, filtered with
  `listContains` on an `acl` metadata list (`orAll` for several groups).
- Group names are checked against a strict pattern before they go into a filter string, and every
  result is re-checked; one outside the caller's groups raises `AccessFilterError`.

The client's index must carry `section_id`, `url`, `heading`, `text` and `acl` (and `embedding` for
Azure).

## Consequences
- **Tested with mocks only.** Azure tests use `httpx.MockTransport` against the documented REST
  shape; Bedrock tests use botocore's `Stubber`, which also validates each request against the
  service's API model. Neither adapter has run against a live service, and their retrieval quality
  has not been measured.
- The benchmark numbers in the README are for the pgvector retriever only.
