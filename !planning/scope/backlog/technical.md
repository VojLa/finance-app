# Technical Backlog

- snapshot rebuild performance at large history depth
- parser architecture tooling for faster new parser delivery
- import idempotence hardening across multi-file retries
- durable asynchronous import queue: an import request persists the upload and
  returns a batch/job identifier without waiting for processing; workers then load
  and normalize rows, post canonical data, rebuild affected snapshots and publish
  the result in the background. The UI can enqueue additional imports immediately
  and track each job through queued, processing, completed and failed states.
  Processing must define idempotent retries, account/user isolation and bounded
  concurrency so multiple queued imports cannot publish out of order or overwrite
  newer canonical state.
- reconciliation workflow and drift detection engine
- Python to Rust data boundary for heavy rebuild jobs
