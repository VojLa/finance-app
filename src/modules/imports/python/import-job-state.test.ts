import { describe, expect, it } from "vitest"

import type { PythonImportJob } from "./import-contract"
import {
  beginImportPoll,
  clearPersistedImportJob,
  finishImportPoll,
  importPollDelayMs,
  loadLatestPersistedImportJob,
  persistImportJob,
  resolveImportPollFailure,
  resolveImportPollJob,
} from "./import-job-state"

describe("import poll single-flight gate", () => {
  it("queues one immediate follow-up when a visibility wake overlaps an in-flight poll", () => {
    const gate = { inFlight: false, pending: false }

    expect(beginImportPoll(gate)).toBe(true)
    expect(beginImportPoll(gate)).toBe(false)
    expect(beginImportPoll(gate)).toBe(false)
    expect(finishImportPoll(gate)).toBe(true)
    expect(beginImportPoll(gate)).toBe(true)
    expect(finishImportPoll(gate)).toBe(false)
  })

  it("classifies every validated lifecycle state without publishing partial progress", () => {
    expect(resolveImportPollJob(job("account-a", "queued", "2026-01-01T00:00:00Z"))).toEqual({
      kind: "continue",
      runAfter: null,
    })
    expect(
      resolveImportPollJob({
        ...job("account-a", "retry", "2026-01-01T00:00:00Z"),
        status: "retry_wait",
        error: { code: "provider_unavailable", message: "Try again later." },
      })
    ).toEqual({ kind: "continue", runAfter: "2026-01-01T00:00:00Z" })
    expect(
      resolveImportPollJob({
        ...job("account-a", "failed", "2026-01-01T00:00:00Z"),
        status: "failed",
        error: { code: "import_failed", message: "Import failed." },
        finished_at: "2026-01-01T00:01:00Z",
      })
    ).toEqual({ kind: "failed" })

    const completed = job("account-a", "completed", "2026-01-01T00:00:00Z")
    completed.status = "completed"
    completed.progress.phase = "completed"
    completed.progress.completed_units = completed.progress.total_units
    completed.progress.completed_batches = completed.progress.total_batches
    completed.result = {
      schema_version: 1,
      batch_ids: ["batch-a"],
      rows_imported: 1,
      rows_skipped: 0,
      rows_total: 1,
      snapshot_refresh_status: "created",
      completed_at: "2026-01-01T00:01:00Z",
    }
    completed.finished_at = "2026-01-01T00:01:00Z"
    expect(resolveImportPollJob(completed)).toEqual({ kind: "completed" })
  })

  it("discards only a scoped not-found response and retries auth, server, and network failures", () => {
    expect(resolveImportPollFailure(404)).toBe("discard")
    expect(resolveImportPollFailure(401)).toBe("retry")
    expect(resolveImportPollFailure(502)).toBe("retry")
    expect(resolveImportPollFailure(null)).toBe("retry")
  })
})

function job(accountId: string, id: string, createdAt: string): PythonImportJob {
  return {
    id,
    account_id: accountId,
    kind: "import_workflow",
    status: "queued",
    progress: {
      schema_version: 1,
      phase: "queued",
      completed_units: 0,
      total_units: 7,
      completed_batches: 0,
      total_batches: 1,
    },
    result: null,
    error: null,
    attempt_count: 0,
    max_attempts: 5,
    manual_retry_count: 0,
    run_after: createdAt,
    started_at: null,
    finished_at: null,
    created_at: createdAt,
    updated_at: createdAt,
  }
}

function memoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    get length() {
      return values.size
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  }
}

describe("durable import job browser state", () => {
  it("isolates records by user and account and resumes the newest valid record", () => {
    const storage = memoryStorage()
    persistImportJob(storage, "user-a", job("account-a", "job-a", "2026-01-01T00:00:00Z"))
    const newest = persistImportJob(
      storage,
      "user-a",
      job("account-b", "job-b", "2026-01-02T00:00:00Z")
    )
    persistImportJob(storage, "user-b", job("account-c", "job-c", "2026-01-03T00:00:00Z"))

    const now = Date.parse("2026-01-03T00:00:00Z")
    expect(loadLatestPersistedImportJob(storage, "user-a", now)).toEqual(newest)
    expect(loadLatestPersistedImportJob(storage, "user-b", now)?.jobId).toBe("job-c")
    clearPersistedImportJob(storage, newest)
    expect(loadLatestPersistedImportJob(storage, "user-a", now)?.jobId).toBe("job-a")
  })

  it("removes malformed scoped records without touching another user", () => {
    const storage = memoryStorage()
    persistImportJob(storage, "user-b", job("account-b", "job-b", "2026-01-01T00:00:00Z"))
    storage.setItem("finance-app.import-job.v1:user-a:account-a", '{"version":1}')

    const now = Date.parse("2026-01-02T00:00:00Z")
    expect(loadLatestPersistedImportJob(storage, "user-a", now)).toBeNull()
    expect(loadLatestPersistedImportJob(storage, "user-b", now)?.jobId).toBe("job-b")
  })

  it("discards stale and implausibly future records before a resume", () => {
    const storage = memoryStorage()
    persistImportJob(storage, "user-a", job("account-old", "job-old", "2025-12-01T00:00:00Z"))
    persistImportJob(storage, "user-a", job("account-new", "job-new", "2026-02-01T00:00:00Z"))

    expect(
      loadLatestPersistedImportJob(storage, "user-a", Date.parse("2026-01-01T00:00:00Z"))
    ).toBeNull()
    expect(storage.length).toBe(0)
  })

  it("uses independent transient-failure backoff and clamps retry_wait", () => {
    expect(importPollDelayMs(0, null, 0)).toBe(1_000)
    expect(importPollDelayMs(3, null, 0)).toBe(8_000)
    expect(importPollDelayMs(99, null, 0)).toBe(12_000)
    expect(importPollDelayMs(0, "2026-01-01T00:01:00Z", Date.parse("2026-01-01T00:00:00Z"))).toBe(
      15_000
    )
    expect(importPollDelayMs(4, null, 0, true)).toBe(0)
  })
})
