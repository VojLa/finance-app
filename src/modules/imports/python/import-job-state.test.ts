import { describe, expect, it } from "vitest"

import type { PythonImportJob } from "./import-contract"
import {
  beginImportPoll,
  clearPersistedImportJob,
  finishImportPoll,
  importPollDelayMs,
  loadLatestPersistedImportJob,
  persistImportJob,
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
