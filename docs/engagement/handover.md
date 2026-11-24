# Handover

## What was delivered
- A support assistant over the PostgreSQL 18 docs and the desk's internal notes: a LangGraph flow
  (redact → retrieve → grade → answer → check citations) with Claude Haiku grading and Claude Sonnet
  writing, answers cited to the section, refusals when nothing relevant is found.
- Retrieval on Postgres: pgvector, full-text search and RRF hybrid behind a LangChain retriever,
  with access control inside the query. Adapters for Azure AI Search and Bedrock Knowledge Bases
  (tested with mocks).
- An API with per-person tokens and roles, a redacted answer log, rate limits, and the Support Desk
  console showing each answer beside its evidence.
- Terraform for Azure Container Apps and AWS ECS Fargate, validated offline, not applied.
- CI: lint, strict types, 97 tests with an 80% coverage gate (about 96%), Terraform checks,
  gitleaks, Semgrep, SBOM, and a container smoke test that checks access control.

## Measured
| | Result | Evidence |
|---|---|---|
| Retrieval, 50 answerable questions | hit@5: vector 46, hybrid 44, keyword 41 | `bench/results.json` |
| Access control | 576 searches as every role: 0 restricted results; 0 restricted facts in answers | `bench/results.json` |
| End to end | 46 of 50 answerable answered (43 citing a gold section); 8 of 8 unanswerable and 5 of 6 restricted refused; median 8.4 s | `bench/answers.json` |
| Answer accuracy | 0 wrong statements in 47 answers; 7 incomplete, each saying what it could not cover | `bench/hand_check.md` (Claude); a person's review of 10 is pending (`bench/spot_check.md`) |

## What is not done
| Item | Why it matters | Suggested next step |
|---|---|---|
| Real tickets | The questions were written for the benchmark | Collect 100 anonymised tickets in the pilot and re-run |
| Chunk selection | One chunk per section misses answers in long sections (Q03, Q42) | Keep the best two chunks per section; split tables by row |
| Retrieval tuning | Fusion and keyword ranking were not tuned, to keep the test set honest | Tune on a separate development set |
| Name detection | Pattern redaction misses names in free text | Add a model-based detector (Presidio) behind the same interface |
| Managed search | Azure AI Search and Bedrock adapters are tested with mocks only | Run the benchmark against a client index |
| Model gateway | No Bedrock or Azure chat adapter | Point `LLM_PROXY_URL` at the client's gateway, or add an adapter |
| Per-user access | Tokens are shared secrets per person | SSO (Entra ID / Okta) at the ingress, roles from group claims |
| Retention | Answer log kept indefinitely | Scheduled deletion after 90 days |
| Deployment | Terraform validated, never applied | Apply to a sandbox, run the index job, then the smoke test there |

## Where to start reading
`src/support_knowledge_assistant/agent.py` (the flow), `retrieve.py` (search and the access filter),
then `docs/adr/` and `bench/hand_check.md`.
