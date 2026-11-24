# 3. Access control inside the retrieval query, not after it

Status: accepted

## Context
The desk's notes have three levels: public documentation, support macros (plan limits, the pooler
port, escalation rules) and SRE runbooks (failover, break-glass access, incident reviews with
customer details). Customers will use the assistant through the portal, support staff through the
console. A customer must never receive a support or SRE note, and a support agent never an SRE one.

Filtering after retrieval ("fetch the top 10, drop what they may not see") has two problems: the
restricted text has already been read into the process and may reach a model or a log, and the
asker gets fewer, worse results whenever restricted notes rank highly.

## Decision
- Each section carries an access list (`acl`), set at build time. Internal notes must declare a
  non-public one or the build fails.
- A token maps to a name and a role; a role maps to groups (`customer` → public;
  `support` → public, support; `sre` → all). Nothing in a request can change it.
- Both SQL queries filter with `acl && :groups` before ranking. A restricted chunk is never a
  candidate.
- `search()` re-checks every hit and raises if one is outside the groups. The managed-search
  adapters push the same filter into Azure AI Search (OData `search.in`) and Bedrock (`listContains`)
  and apply the same re-check (ADR 6).
- Refusals use one wording whatever the reason (ADR 1).

## Consequences
- The leak check runs every one of the 64 questions as every role in every mode: 576 searches, 0
  restricted results. End to end, 0 answers contained a marker string from a note above the asker's
  level (canaries planted in each SRE note, and facts that exist only in support notes).
- The CI smoke test repeats the check through the running container stack.
- A question whose answer exists only in a restricted note gets a public answer if the public docs
  cover it (Q60: failover steps from the public docs, not the runbook) or a refusal if not.
- Group changes need a re-index (cheap: unchanged chunks keep their embeddings).
