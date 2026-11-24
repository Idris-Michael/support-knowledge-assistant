# Runbook

## Start locally
```bash
cp .env.example .env            # set API_TOKENS (one per person) and LLM_MODE
ollama pull nomic-embed-text     # embeddings, on the host
docker compose up -d --build     # Postgres, migrations, index, API + console on :8080, Jaeger on :16686
```
With `LLM_MODE=proxy`, start the model proxy on the host first: `uv run ska-llm-proxy` (it needs
`LLM_PROXY_TOKEN` in `.env` and a logged-in `claude` CLI).

## Update the documents
```bash
uv run ska corpus fetch          # only pages not already in corpus/raw/; writes corpus/manifest.json
uv run ska corpus build          # corpus/sections.jsonl (internal notes redacted here)
uv run ska index                 # embeds changed chunks only
uv run python bench/retrieval.py # check retrieval did not get worse
```
Internal notes live in `corpus/internal/*.md` with a `title:` and an `acl:` header. A note without a
non-public `acl` stops the build.

## Add or remove a user
Edit the `API_TOKENS` JSON (Key Vault secret `api-tokens` / Secrets Manager `<name>/api-tokens`) and
restart the API. Generate tokens with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

## Symptoms
| Symptom | Likely cause | What to do |
|---|---|---|
| `/healthz` 503 "index is empty" | Index job has not run | Run the index job (`docker compose run --rm index`, or the cloud job) |
| Every question refused with `no_documents` | Embedding model not reachable, or wrong `RETRIEVE_MODE` | Check `OLLAMA_URL` from the API container; `ollama list` on the host |
| 502 "assistant is unavailable" | Model proxy or gateway down, or CLI not logged in | Check the proxy log; `claude -p "hi"` on the host |
| Connections to Postgres hang for about two minutes on Windows | `localhost` tries IPv6 first and the port is bound to IPv4 only | Use `127.0.0.1` in `DATABASE_URL` |
| Many `model_declined` refusals after a document update | Sections grew past the chunk size; the chunk kept is not the one with the answer | Re-run `bench/answers.py` and compare; see ADR 2 |
| 429 | Per-caller rate limit | Raise `RATE_LIMIT_PER_MINUTE` or spread the load |

## Benchmarks
- `bench/retrieval.py`: three retrieval modes plus the leak check; about 30 s, no model calls.
- `bench/answers.py`: all 64 questions end to end, one at a time; 512 s and 322,606 model tokens
  in the recorded run with Claude (nearly all input: the retrieved sources). `bench/answers.py Q01 Q02` runs a
  subset.
Record results in `bench/results.json` and the README; do not edit `bench/questions.jsonl` to fit
a result.
