# 001 – Training Logger

A lightweight specification for recording model training sessions into a persistent store so that we can audit, analyse, and debug BoxerBrain training runs.

## Motivation

We run multiple training jobs in containers across the cluster. Without a central record it is difficult to answer questions such as:

* What hyperparameters were used for a given model version?
* Which container produced the lowest loss?
* When did a particular training session start and finish?

A `training_logs` table will provide a single source of truth and allow dashboards, alerts, and retrospective analysis.

## Goals

1. Define the schema for a relational store (PostgreSQL) to track sessions.
2. Provide a minimal API for workers to insert records.
3. Ensure the table is extensible (additional columns can be added later).
4. Store the raw configuration as JSON for future processing.

## Non‑goals

* Performing real‑time analytics or streaming. This is a simple write‑only log.
* Integrating with external monitoring tools – that will be built on top of the data.
* Historical versioning of the schema beyond the UUID primary key.

## Schema

The table is called `training_logs`. Each row represents one run of a training job.

| Column | Type | Description |
| :--- | :--- | :--- |
| id | uuid | Primary Key (gen_random_uuid()) |
| created_at | timestamp | Start time of the session |
| model_version | text | Version of BoxerBrain being trained |
| config | jsonb | Hyperparameters (learning_rate, batch_size, etc.) |
| final_loss | float4 | The training loss at completion |
| container_id | text | The Docker ID of the worker node (UNIQUE) |

Additional columns may be appended later (e.g. `duration`, `status`, `metrics`).

## API

Workers should POST a JSON payload to the internal `/api/train-log` endpoint:

```http
POST /api/train-log
Content-Type: application/json

{
  "model_version": "v1.2.3",
  "config": { "learning_rate": 0.001, "batch_size": 64 },
  "final_loss": 0.023,
  "container_id": "abc123"
}
```

The service will add `id` and `created_at` on insert and return the full row.

## Implementation notes

* Use `gen_random_uuid()` default for `id`.
* Index on `model_version` for lookup.
* The API should be idempotent; re‑posting the same container ID within a short window should return the existing record. Implement this by declaring `container_id` UNIQUE and using `ON CONFLICT (container_id) DO UPDATE` to avoid duplicate rows.

## Next steps / tasks

1. Create migration for `training_logs` table.
2. Implement the HTTP handler and database client.
3. Add basic unit tests and a CLI helper to replay logs.
4. Wire up a dashboard to visualize recent runs.

---

*Proposal drafted by the opsx generator.*