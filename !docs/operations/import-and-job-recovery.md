# Import and job recovery

Type: runbook
Status: current
Owns: safe recovery expectations for durable import work
Code: `modules/imports/`, `modules/jobs/` and import worker
Update when: job state, retry, fencing or publication behavior changes

## Preconditions

- Identify the account, persisted import batch and durable job through the safe API.
- Confirm the worker and database are ready; a stopped browser poll is not job failure.
- Preserve the uploaded file and persisted batch/row/issue evidence.

## Recovery

1. Read job status and stable error evidence.
2. If the job is retryable, use only the job retry endpoint or UI action.
3. Observe the same job through terminal success/failure; do not re-upload or manually
   execute posting stages in parallel.
4. Verify published snapshot/current evidence only after the job reports completion.

The worker replays idempotent stages and publication stays fenced at the last complete
baseline. Stop and investigate persisted evidence if ownership, lease or canonical
lineage is ambiguous. Representative recovery tests are in the
[domain matrix](../domains/imports-and-jobs/testing.md).
