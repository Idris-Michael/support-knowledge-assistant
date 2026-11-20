---
title: Extensions policy
acl: support, sre
---
FICTIONAL: written for the Larkspur Data pilot. Not a real company's policy.

## Allowed extensions
Customers can run CREATE EXTENSION themselves for: pg_stat_statements, pgvector (named vector),
postgis, pg_trgm, btree_gin, btree_gist, citext, hstore, uuid-ossp, pgcrypto, tablefunc and
pg_partman. These are pre-installed on every plan.

## Not allowed
Untrusted procedural languages (plpython3u, plperlu) and anything that reads or writes the server's
file system (adminpack, file_fdw) are never enabled, because they would give a customer access to
the host. Do not offer exceptions; the answer is no on every plan.

## Requests for other extensions
Log the request with the extension name and the customer's use case. Product review happens monthly.
Do not give a date.
