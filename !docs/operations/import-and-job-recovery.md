# Import and job recovery

Type: runbook
Status: current
Owns: safe recovery expectations for durable import work
Code: `modules/imports/`, `modules/jobs/` and import worker
Update when: job state, retry, fencing or publication behavior changes

Identify the persisted batch and durable job through safe API status. Do not
re-upload or manually post merely because browser polling stopped. Retry only
through the durable job path. The worker replays idempotent stages and preserves
batch/row evidence; publication stays fenced at the last complete baseline until
atomic completion. Corrupt evidence or ambiguous ownership fails closed.
