---
title: Severity and escalation
acl: support, sre
---
FICTIONAL: written for the Larkspur Data pilot. Not a real company's policy.

## Severity levels
- Severity 1: a production cluster is down or refusing all connections. First response 15 minutes,
  24/7. Page the on-call SRE immediately.
- Severity 2: production is degraded (replication lag over 5 minutes, disk over 90%). First response
  1 hour, 24/7.
- Severity 3: everything else, including restore requests and questions. First response 1 business
  day.

## How to page the on-call SRE
Use the "Page SRE" button on the ticket; do not phone individuals. Out of hours, the on-call rota is
in the ops calendar; the desk phone extension is 4410. Include the cluster name, the first error seen
and the time it started in UTC.

## What support must not do
Support staff never run commands on customer clusters, never share internal hostnames with customers,
and never promise a root cause before the incident review is published.
