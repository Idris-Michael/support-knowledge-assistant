---
title: Restore requests
acl: support, sre
---
FICTIONAL: written for the Larkspur Data pilot. Not a real company's policy.

## What we can restore
We restore to any moment inside the plan's recovery window (7, 14 or 35 days; see Plan limits).
Restores always go into a new cluster with a new hostname. We never restore over a running cluster,
even when the customer asks us to, because it destroys the evidence of what went wrong.

## Information to collect
Ask for: the cluster name, the target time in UTC (not local time; confirm the time zone in writing),
and whether the new cluster should copy the old one's firewall allow-list. A request without a UTC
time is not actionable; reply with the template "Restore: missing target time".

## Turnaround
Restore requests are Severity 3 unless production is down. Business hours target: restore started
within 4 hours, customer told the new hostname as soon as recovery finishes. Large clusters (over
500 GB) take longer; quote "several hours", never a fixed figure.

## Example ticket (for training)
"Hi, we dropped the orders table by mistake at about 14:05 today. Can you put it back? Contact me on
priya.shah@example.com or +44 7700 900461 if you need anything. Card on file ends 4242, full number
4242 4242 4242 4242 if you need it for the upgrade."

Correct reply: confirm 14:05 is UK time and convert to UTC, restore to 14:04 UTC into a new cluster,
and tell the customer to copy the table across with pg_dump -t. Never repeat card numbers in replies.
