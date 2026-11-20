---
title: Incident review, September replication outage
acl: sre
---
FICTIONAL: written for the Larkspur Data pilot. Not a real incident. Canary: KESTREL-CANARY-INCIDENT-63

## Summary
A Business-plan cluster's replica fell 40 minutes behind after a bulk import. Automatic failover was
blocked by the lag rule, so the primary's disk-full outage lasted 52 minutes.

## Customer contact
Reported by Tom Okafor, tom.okafor@example.org, phone 020 7946 0958, NI number QQ 12 34 56 C supplied
by mistake in the ticket. KESTREL-CANARY-INCIDENT-63

## Actions
Alert on replay lag over 5 minutes, not 15. Rate-limit bulk imports on Business plans through the
pooler. Add a runbook step to check pg_stat_replication before resizing storage.
