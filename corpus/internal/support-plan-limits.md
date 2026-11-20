---
title: Plan limits and connection tickets
acl: support, sre
---
FICTIONAL: written for the Larkspur Data pilot. Not a real company's policy.

## Plan limits
Every managed cluster runs PostgreSQL 18. Limits by plan:

- Starter: max_connections 50, 2 vCPU, 4 GB RAM, point-in-time recovery window 7 days.
- Standard: max_connections 200, 4 vCPU, 16 GB RAM, point-in-time recovery window 14 days.
- Business: max_connections 500, 8 vCPU, 64 GB RAM, point-in-time recovery window 35 days.

Customers cannot change max_connections themselves; it is tied to the plan's memory. The only way to
raise it is a plan upgrade, which takes effect after a restart in the customer's maintenance window.

## Answering "too many clients already" tickets
The error means the cluster hit max_connections. Before suggesting an upgrade, check whether the
customer uses the built-in connection pooler. Every plan includes PgBouncer on port 6432 in
transaction mode; most applications that open a connection per request can switch to it by changing
only the port. Session-level features (prepared statements without protocol support, advisory locks
held across transactions, SET without LOCAL) do not work through transaction pooling, so ask about
those first.

If they already use the pooler and still hit the limit, look for idle-in-transaction sessions in
pg_stat_activity and point them at idle_in_transaction_session_timeout, which they may set per role.
