# Persistent Job Engine

The first queue implementation is a single-device, single-SQLite-database scheduler intended for local processing. It uses atomic claims, expiring leases, idempotency keys, bounded exponential retry and explicit terminal failure.

## Guarantees and limits

- Durable job state survives process restart.
- Claims are serialized with short `BEGIN IMMEDIATE` transactions.
- A lease token prevents an expired worker from acknowledging a job after reclamation.
- Delivery is **at least once**, not exactly once. A worker may finish an external side effect and crash before recording completion. Handlers must therefore be idempotent.
- This is not a multi-host distributed queue. Keep SQLite WAL files on local storage, not network filesystems or cloud-synced folders.
- Retry delays are bounded; exhausted attempts become inspectable FAILED jobs.
- Payloads are JSON objects. Never put credentials, API keys or raw private media in job payloads; store references to protected local assets instead.

## Current API

```python
queue = JobQueue("library/omniintel.db")
job_id = queue.enqueue("transcript.import", {"asset_id": "..."}, idempotency_key="...")
job = queue.claim("worker-1", lease_ms=60_000)
queue.heartbeat(job["id"], job["lease_token"], lease_ms=60_000)
queue.complete(job["id"], job["lease_token"], {"source_id": "..."})
# Or queue.fail(job["id"], job["lease_token"], "reason")
```

This is a foundation, not the full orchestration engine. Stage DAGs, cancellation, resource-aware scheduling, durable events/outbox, progress reporting and platform-specific workers remain future work.
