---
title: Manual failover runbook
acl: sre
---
FICTIONAL: written for the Larkspur Data pilot. Not a real company's runbook. Canary: KESTREL-CANARY-FAILOVER-41

## When to fail over manually
Only when automatic failover has not happened within 5 minutes of the primary becoming unreachable,
and the replica's replay lag was under 30 seconds before the outage. Otherwise escalate to the
database lead; a manual failover with high lag loses committed transactions.

## Steps
1. Fence the old primary: remove it from the load balancer pool lb-int-07 and block port 5432 on its
   security group, so it cannot accept writes if it comes back.
2. On the replica, run pg_ctl promote (or SELECT pg_promote()). Check pg_is_in_recovery() returns false.
3. Point the cluster's DNS record at the promoted node; TTL is 30 seconds.
4. Rebuild a new replica from the promoted primary with pg_basebackup.
5. Post the timeline switch in the incident channel. KESTREL-CANARY-FAILOVER-41
