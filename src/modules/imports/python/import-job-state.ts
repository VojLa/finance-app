import type { PythonImportJob } from "./import-contract"

const STORAGE_PREFIX = "finance-app.import-job.v1"
const POLL_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 12_000] as const
const MAX_RETRY_WAIT_MS = 15_000
const MAX_PERSISTED_JOB_AGE_MS = 7 * 24 * 60 * 60 * 1_000
const MAX_PERSISTED_JOB_FUTURE_SKEW_MS = 5 * 60 * 1_000

export type PersistedImportJob = {
  version: 1
  userId: string
  accountId: string
  jobId: string
  createdAt: string
}

type JobStorage = Pick<Storage, "length" | "key" | "getItem" | "setItem" | "removeItem">

export type ImportPollGate = { inFlight: boolean; pending: boolean }

export function beginImportPoll(gate: ImportPollGate): boolean {
  if (gate.inFlight) {
    gate.pending = true
    return false
  }
  gate.inFlight = true
  return true
}

export function finishImportPoll(gate: ImportPollGate): boolean {
  gate.inFlight = false
  const pending = gate.pending
  gate.pending = false
  return pending
}

function canonical(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value === value.trim()
}

function storageKey(userId: string, accountId: string): string {
  if (!canonical(userId) || !canonical(accountId)) throw new TypeError("Invalid import job scope")
  return `${STORAGE_PREFIX}:${encodeURIComponent(userId)}:${encodeURIComponent(accountId)}`
}

function parseRecord(value: string, key: string): PersistedImportJob {
  const parsed: unknown = JSON.parse(value)
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new TypeError("Invalid persisted import job")
  }
  const record = parsed as Record<string, unknown>
  const expected = ["version", "userId", "accountId", "jobId", "createdAt"].sort()
  const actual = Object.keys(record).sort()
  if (
    actual.length !== expected.length ||
    actual.some((name, index) => name !== expected[index]) ||
    record.version !== 1 ||
    !canonical(record.userId) ||
    !canonical(record.accountId) ||
    !canonical(record.jobId) ||
    !canonical(record.createdAt) ||
    Number.isNaN(Date.parse(record.createdAt)) ||
    key !== storageKey(record.userId, record.accountId)
  ) {
    throw new TypeError("Invalid persisted import job")
  }
  return record as PersistedImportJob
}

export function persistImportJob(
  storage: JobStorage,
  userId: string,
  job: PythonImportJob
): PersistedImportJob {
  const record: PersistedImportJob = {
    version: 1,
    userId,
    accountId: job.account_id,
    jobId: job.id,
    createdAt: job.created_at,
  }
  storage.setItem(storageKey(userId, job.account_id), JSON.stringify(record))
  return record
}

export function clearPersistedImportJob(storage: JobStorage, record: PersistedImportJob): void {
  storage.removeItem(storageKey(record.userId, record.accountId))
}

export function loadLatestPersistedImportJob(
  storage: JobStorage,
  userId: string,
  now = Date.now()
): PersistedImportJob | null {
  if (!canonical(userId)) return null
  const prefix = `${STORAGE_PREFIX}:${encodeURIComponent(userId)}:`
  const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index)).filter(
    (key): key is string => typeof key === "string" && key.startsWith(prefix)
  )
  let latest: PersistedImportJob | null = null
  for (const key of keys) {
    const value = storage.getItem(key)
    if (value === null) continue
    try {
      const record = parseRecord(value, key)
      if (record.userId !== userId) throw new TypeError("Foreign persisted import job")
      const createdAt = Date.parse(record.createdAt)
      if (
        createdAt > now + MAX_PERSISTED_JOB_FUTURE_SKEW_MS ||
        createdAt < now - MAX_PERSISTED_JOB_AGE_MS
      ) {
        throw new TypeError("Expired persisted import job")
      }
      if (latest === null || Date.parse(record.createdAt) > Date.parse(latest.createdAt)) {
        latest = record
      }
    } catch {
      storage.removeItem(key)
    }
  }
  return latest
}

export function importPollDelayMs(
  failureCount: number,
  runAfter: string | null,
  now: number,
  immediate = false
): number {
  if (immediate) return 0
  const boundedFailures = Math.max(0, Math.min(Math.trunc(failureCount), POLL_DELAYS_MS.length - 1))
  const base = POLL_DELAYS_MS[boundedFailures]
  const scheduled =
    runAfter === null || Number.isNaN(Date.parse(runAfter))
      ? 0
      : Math.max(0, Math.min(MAX_RETRY_WAIT_MS, Date.parse(runAfter) - now))
  return Math.max(base, scheduled)
}
