import { describe, expect, it } from "vitest"

import { parseImportJob, type PythonImportJob } from "./import-contract"

function job(): PythonImportJob {
  return {
    id: "job-a",
    account_id: "account-a",
    kind: "import_workflow",
    status: "queued",
    progress: {
      schema_version: 1,
      phase: "queued",
      completed_units: 0,
      total_units: 7,
      completed_batches: 0,
      total_batches: 2,
    },
    result: null,
    error: null,
    attempt_count: 0,
    max_attempts: 5,
    manual_retry_count: 0,
    run_after: "2026-01-01T00:00:00Z",
    started_at: null,
    finished_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  }
}

function copy(value: PythonImportJob): PythonImportJob {
  return JSON.parse(JSON.stringify(value)) as PythonImportJob
}

describe("ImportJob browser contract", () => {
  it("accepts only the documented queued response shape", () => {
    expect(parseImportJob(job())).toMatchObject({ id: "job-a", status: "queued" })
  })

  it.each(["reconciling", "acquiring_reporting_fx", "validating_liability"] as const)(
    "accepts the durable %s progress phase",
    (phase) => {
      const value = copy(job())
      value.status = "running"
      value.progress.phase = phase
      expect(parseImportJob(value).progress.phase).toBe(phase)
    }
  )

  it("fails closed on unknown fields, identity, enum, counters and dates", () => {
    const cases: unknown[] = [
      { ...job(), internal_trace: "secret" },
      { ...job(), id: " job-a" },
      { ...job(), kind: "another_job" },
      { ...job(), status: "unknown" },
      { ...job(), progress: { ...job().progress, phase: "unknown" } },
      { ...job(), progress: { ...job().progress, completed_units: 8 } },
      { ...job(), progress: { ...job().progress, total_batches: 11 } },
      { ...job(), run_after: "not-a-date" },
      { ...job(), attempt_count: 6 },
    ]
    for (const value of cases) expect(() => parseImportJob(value)).toThrow(TypeError)
  })

  it("requires complete terminal evidence and accepts the safe retry_wait error", () => {
    const completed = copy(job())
    completed.status = "completed"
    completed.progress.phase = "completed"
    completed.progress.completed_units = 7
    completed.progress.completed_batches = 2
    completed.finished_at = "2026-01-01T00:01:00Z"
    completed.result = {
      schema_version: 1,
      batch_ids: ["batch-a", "batch-b"],
      rows_total: 3,
      rows_imported: 2,
      rows_skipped: 1,
      snapshot_refresh_status: "created",
      completed_at: "2026-01-01T00:01:00Z",
    }
    expect(parseImportJob(completed)).toMatchObject({ status: "completed" })

    const retryWaiting = copy(job())
    retryWaiting.status = "retry_wait"
    retryWaiting.error = {
      code: "import_publication_deferred",
      message: "Portfolio publication is waiting for its reserved snapshot window.",
    }
    expect(parseImportJob(retryWaiting)).toMatchObject({
      status: "retry_wait",
      error: { code: "import_publication_deferred" },
    })

    const failed = copy(job())
    failed.status = "failed"
    failed.progress.phase = "validating_liability"
    failed.progress.completed_units = 6
    failed.progress.completed_batches = 2
    failed.attempt_count = 1
    failed.started_at = "2026-08-19T21:48:06.762000"
    failed.finished_at = "2026-08-19T21:48:10.887000"
    failed.error = {
      code: "import_job_validation_failed",
      message: "The import job cannot continue with the persisted input.",
    }
    expect(parseImportJob(failed)).toMatchObject({
      status: "failed",
      progress: { phase: "validating_liability" },
      error: { code: "import_job_validation_failed" },
    })

    const invalidTerminalStates = [
      { ...completed, error: { code: "oops", message: "No." } },
      { ...job(), status: "failed" },
      { ...job(), status: "retry_wait" },
      { ...completed, result: { ...completed.result, batch_ids: ["batch-b", "batch-a"] } },
    ]
    for (const value of invalidTerminalStates)
      expect(() => parseImportJob(value)).toThrow(TypeError)
  })
})
