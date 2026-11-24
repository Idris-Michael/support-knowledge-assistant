# Infrastructure (deploy-ready, not deployed)

Two equivalent targets for the same image. Both are checked in CI with `terraform validate`, tflint
and checkov; neither has been applied. Every checkov skip carries its reason inline.

| | Azure (`azure/`) | AWS (`aws/`) |
|---|---|---|
| API | Container App, external ingress | ECS Fargate service behind an HTTPS ALB |
| Embeddings | Ollama as its own Container App, internal ingress only | Ollama sidecar in each task, on localhost |
| Migrations + index | Container Apps Job, manual trigger | One-off `run-task` with a command override (see outputs) |
| Database | Postgres Flexible Server, VNet-injected, `azure.extensions = VECTOR` | RDS Postgres (pgvector built in), private subnets, KMS |
| Secrets | Key Vault (RBAC), read by a user-assigned identity | Secrets Manager under a customer-managed KMS key |
| Logs | Log Analytics | CloudWatch Logs, 365 days, KMS |

**Why Ollama goes with the app.** The index and every query must use the same embedding model, or
vector search compares unlike things. Running nomic-embed-text next to the app (CPU is enough at
this size; 274 MB) keeps that true without a second vendor. On Azure it is a separate internal app
because a Container Apps Job with a never-ending sidecar would never complete; on AWS the sidecar is
non-essential, so a one-off index task stops when the app container exits.

**Models.** The answer and grading models are reached through `LLM_PROXY_URL`, the
`ska-llm-proxy` API (`POST /v1/complete`). In a client environment that is their model gateway (for
example in front of Claude on Amazon Bedrock or Azure AI Foundry). No Bedrock or Azure chat adapter is
in this repo.

**Secrets.** `api-tokens` and `llm-proxy-token` are placeholders in Terraform and are set out of band
after apply, so they never sit in state. The database URL is generated and stored by Terraform, so it
does sit in state: keep state in an encrypted backend with restricted access.

**Managed search instead of pgvector.** To use a client's Azure AI Search index or Bedrock Knowledge
Base, set `RETRIEVER` and its settings (see `src/support_knowledge_assistant/adapters.py`); the
index must carry `section_id`, `url`, `heading`, `text` and an `acl` collection. Those adapters are
tested with mocks only.

After each release: run the index job, then roll the API.
