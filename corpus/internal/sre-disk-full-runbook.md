---
title: Disk full runbook
acl: sre
---
FICTIONAL: written for the Larkspur Data pilot. Not a real company's runbook. Canary: KESTREL-CANARY-DISK-17

## First check: is it WAL?
Most disk-full pages on our platform are pg_wal growing, not table data. Run
SELECT slot_name, active, wal_status, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn))
FROM pg_replication_slots; an inactive slot holding back tens of gigabytes is the usual cause.

## Fix for an abandoned slot
Confirm with the customer's account owner that the consumer (often a stopped CDC tool) is gone, then
drop the slot with pg_drop_replication_slot. Our platform sets max_slot_wal_keep_size to 20% of the
volume, so a slot is invalidated before the disk fills; if it still filled, the setting was changed
by hand and must be reset. KESTREL-CANARY-DISK-17

## If it is table data
Grow the volume online (ops console, "Resize storage"); never delete files from the data directory.
