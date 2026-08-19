import type { components } from "@/generated/python-api"

export type PythonImportBatchCreateRequest = components["schemas"]["ImportBatchCreateRequest"]
export type PythonImportBatch = components["schemas"]["ImportBatchResponse"]
export type PythonImportRegistration =
  | components["schemas"]["ImportRegistrationUploadRequiredResponse"]
  | components["schemas"]["ImportRegistrationResumeJobResponse"]
export type PythonImportUploadResponse = components["schemas"]["ImportUploadResponse"]
export type PythonImportJob = components["schemas"]["ImportJobResponse"]
export type PythonImportJobStatus = components["schemas"]["BackgroundJobStatus"]
export type ImportJobAcceptance = {
  outcome: "started" | "resumed"
  job: PythonImportJob
  acceptedBatchIds: readonly string[]
  rejectedFiles: readonly { filename: string; code: string; message: string }[]
}
export type PythonImportSource = Extract<
  components["schemas"]["ImportSource"],
  "raiffeisenbank" | "trading212" | "anycoin"
>
export type PythonImportStatus = components["schemas"]["ImportStatus"]

export const IMPORT_SOURCES = ["raiffeisenbank", "trading212", "anycoin"] as const
export const IMPORT_STATUSES = [
  "pending",
  "processing",
  "completed",
  "failed",
  "partially_completed",
  "cancelled",
] as const satisfies readonly PythonImportStatus[]

export type ImportPublicError = {
  code: string
  message: string
}

export type ImportApiErrorResponse = { error: ImportPublicError }

export function isPythonImportSource(value: unknown): value is PythonImportSource {
  return typeof value === "string" && IMPORT_SOURCES.includes(value as PythonImportSource)
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false
  }
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function stringField(value: Record<string, unknown>, name: string): string {
  const field = value[name]
  if (typeof field !== "string" || field.trim().length === 0) {
    throw new TypeError(`Invalid ${name}`)
  }
  return field
}

function countField(value: Record<string, unknown>, name: string): number {
  const field = value[name]
  if (!Number.isInteger(field) || (field as number) < 0 || (field as number) > 1_000_000_000) {
    throw new TypeError(`Invalid ${name}`)
  }
  return field as number
}

function nullableCountField(value: Record<string, unknown>, name: string): number | null {
  return value[name] === null ? null : countField(value, name)
}

function importStatus(value: unknown): PythonImportStatus {
  if (typeof value !== "string" || !IMPORT_STATUSES.includes(value as PythonImportStatus)) {
    throw new TypeError("Invalid import status")
  }
  return value as PythonImportStatus
}

function importSource(value: unknown): components["schemas"]["ImportSource"] {
  if (
    typeof value !== "string" ||
    ![...IMPORT_SOURCES, "manual"].includes(value as components["schemas"]["ImportSource"])
  ) {
    throw new TypeError("Invalid import source")
  }
  return value as components["schemas"]["ImportSource"]
}

function nullableString(value: Record<string, unknown>, name: string): string | null {
  const field = value[name]
  if (field !== null && typeof field !== "string") {
    throw new TypeError(`Invalid ${name}`)
  }
  return field as string | null
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
}

function dateField(value: Record<string, unknown>, name: string): string {
  const field = stringField(value, name)
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$/.test(field) ||
    Number.isNaN(Date.parse(field))
  ) {
    throw new TypeError(`Invalid ${name}`)
  }
  return field
}

function nullableDateField(value: Record<string, unknown>, name: string): string | null {
  const field = nullableString(value, name)
  if (
    field !== null &&
    (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$/.test(field) ||
      Number.isNaN(Date.parse(field)))
  ) {
    throw new TypeError(`Invalid ${name}`)
  }
  return field
}

const JOB_STATUSES = ["queued", "running", "retry_wait", "completed", "failed"] as const
const JOB_PHASES = [
  "queued",
  "parsing",
  "normalizing",
  "deduplicating",
  "classifying",
  "posting",
  "reconciling",
  "acquiring_reporting_fx",
  "validating_liability",
  "rebuilding_holdings",
  "refreshing_snapshot",
  "completed",
] as const

export function parseImportJob(value: unknown): PythonImportJob {
  if (!isPlainObject(value)) throw new TypeError("Invalid import job")
  const keys = [
    "id",
    "account_id",
    "kind",
    "status",
    "progress",
    "result",
    "error",
    "attempt_count",
    "max_attempts",
    "manual_retry_count",
    "run_after",
    "started_at",
    "finished_at",
    "created_at",
    "updated_at",
  ] as const
  if (!exactKeys(value, keys)) throw new TypeError("Invalid import job fields")
  const id = stringField(value, "id")
  const accountId = stringField(value, "account_id")
  if (
    id !== id.trim() ||
    id.length > 255 ||
    accountId !== accountId.trim() ||
    accountId.length > 255 ||
    value.kind !== "import_workflow"
  ) {
    throw new TypeError("Invalid import job identity")
  }
  if (
    typeof value.status !== "string" ||
    !JOB_STATUSES.includes(value.status as (typeof JOB_STATUSES)[number])
  ) {
    throw new TypeError("Invalid import job status")
  }
  if (!isPlainObject(value.progress)) throw new TypeError("Invalid import job progress")
  const progressKeys = [
    "schema_version",
    "phase",
    "completed_units",
    "total_units",
    "completed_batches",
    "total_batches",
  ] as const
  if (
    !exactKeys(value.progress, progressKeys) ||
    value.progress.schema_version !== 1 ||
    typeof value.progress.phase !== "string" ||
    !JOB_PHASES.includes(value.progress.phase as (typeof JOB_PHASES)[number])
  ) {
    throw new TypeError("Invalid import job progress")
  }
  const completedUnits = countField(value.progress, "completed_units")
  const totalUnits = countField(value.progress, "total_units")
  const completedBatches = countField(value.progress, "completed_batches")
  const totalBatches = countField(value.progress, "total_batches")
  if (
    totalUnits < 1 ||
    totalBatches < 1 ||
    totalBatches > 10 ||
    completedUnits > totalUnits ||
    completedBatches > totalBatches
  ) {
    throw new TypeError("Invalid import job progress counters")
  }

  let result: PythonImportJob["result"] = null
  if (value.result !== null) {
    if (!isPlainObject(value.result)) throw new TypeError("Invalid import job result")
    const resultKeys = [
      "schema_version",
      "batch_ids",
      "rows_total",
      "rows_imported",
      "rows_skipped",
      "snapshot_refresh_status",
      "completed_at",
    ] as const
    if (
      !exactKeys(value.result, resultKeys) ||
      value.result.schema_version !== 1 ||
      !Array.isArray(value.result.batch_ids) ||
      value.result.batch_ids.length < 1 ||
      value.result.batch_ids.length > 10 ||
      value.result.batch_ids.some(
        (batchId) =>
          typeof batchId !== "string" ||
          !batchId ||
          batchId.length > 255 ||
          batchId !== batchId.trim()
      ) ||
      value.result.batch_ids.some(
        (batchId, index, batchIds) => index > 0 && batchId <= batchIds[index - 1]
      ) ||
      !["created", "replayed", "not_required"].includes(
        value.result.snapshot_refresh_status as string
      )
    ) {
      throw new TypeError("Invalid import job result")
    }
    const rowsTotal = countField(value.result, "rows_total")
    const rowsImported = countField(value.result, "rows_imported")
    const rowsSkipped = countField(value.result, "rows_skipped")
    if (rowsImported + rowsSkipped !== rowsTotal) {
      throw new TypeError("Invalid import job result counters")
    }
    dateField(value.result, "completed_at")
    result = value.result as PythonImportJob["result"]
  }

  let error: PythonImportJob["error"] = null
  if (value.error !== null) {
    if (
      !isPlainObject(value.error) ||
      !exactKeys(value.error, ["code", "message"]) ||
      stringField(value.error, "code").length > 100 ||
      stringField(value.error, "message").length > 1000 ||
      /[\r\n]/.test(stringField(value.error, "code")) ||
      /[\r\n]/.test(stringField(value.error, "message"))
    ) {
      throw new TypeError("Invalid import job error")
    }
    error = value.error as PythonImportJob["error"]
  }

  const attemptCount = countField(value, "attempt_count")
  const maxAttempts = countField(value, "max_attempts")
  const manualRetryCount = countField(value, "manual_retry_count")
  if (maxAttempts < 1 || attemptCount > maxAttempts) {
    throw new TypeError("Invalid import job attempts")
  }
  const runAfter = dateField(value, "run_after")
  const startedAt = nullableDateField(value, "started_at")
  const finishedAt = nullableDateField(value, "finished_at")
  const createdAt = dateField(value, "created_at")
  const updatedAt = dateField(value, "updated_at")
  const completed = value.status === "completed"
  const failed = value.status === "failed"
  const retryWaiting = value.status === "retry_wait"
  const terminal = completed || failed
  if (
    completed !== (result !== null) ||
    (completed && error !== null) ||
    (failed && error === null) ||
    (retryWaiting && error === null) ||
    terminal !== (finishedAt !== null) ||
    (completed &&
      (value.progress.phase !== "completed" ||
        completedUnits !== totalUnits ||
        completedBatches !== totalBatches ||
        result?.batch_ids.length !== totalBatches))
  ) {
    throw new TypeError("Invalid terminal import job state")
  }
  return {
    id,
    account_id: accountId,
    kind: "import_workflow",
    status: value.status as PythonImportJob["status"],
    progress: value.progress as PythonImportJob["progress"],
    result,
    error,
    attempt_count: attemptCount,
    max_attempts: maxAttempts,
    manual_retry_count: manualRetryCount,
    run_after: runAfter,
    started_at: startedAt,
    finished_at: finishedAt,
    created_at: createdAt,
    updated_at: updatedAt,
  }
}

/** Reject any registration shape that could leak non-public durable-job internals. */
export function parseImportRegistration(value: unknown): PythonImportRegistration {
  if (!isPlainObject(value) || !exactKeys(value, ["status", "batch", "job"])) {
    throw new TypeError("Invalid import registration")
  }
  if (value.status === "upload_required" && value.job === null) {
    return {
      status: "upload_required",
      batch: parseImportBatch(value.batch),
      job: null,
    }
  }
  if (value.status === "resume_job" && value.batch === null) {
    return {
      status: "resume_job",
      batch: null,
      job: parseImportJob(value.job),
    }
  }
  throw new TypeError("Invalid import registration")
}

export function parseImportBatch(value: unknown): PythonImportBatch {
  if (!isPlainObject(value)) throw new TypeError("Invalid import batch")
  const createdAt = stringField(value, "created_at")
  if (Number.isNaN(Date.parse(createdAt))) throw new TypeError("Invalid created_at")
  const completedAt = nullableString(value, "completed_at")
  if (completedAt !== null && Number.isNaN(Date.parse(completedAt))) {
    throw new TypeError("Invalid completed_at")
  }
  const fileSize = nullableCountField(value, "file_size")
  return {
    id: stringField(value, "id"),
    account_id: stringField(value, "account_id"),
    source: importSource(value.source),
    filename: stringField(value, "filename"),
    file_size: fileSize,
    file_encoding: nullableString(value, "file_encoding"),
    checksum: stringField(value, "checksum"),
    status: importStatus(value.status),
    rows_total: nullableCountField(value, "rows_total"),
    rows_imported: nullableCountField(value, "rows_imported"),
    rows_skipped: nullableCountField(value, "rows_skipped"),
    created_at: createdAt,
    completed_at: completedAt,
  }
}

export function parseImportUpload(value: unknown): PythonImportUploadResponse {
  if (!isPlainObject(value)) throw new TypeError("Invalid upload response")
  if (typeof value.stored !== "boolean" || typeof value.idempotent !== "boolean") {
    throw new TypeError("Invalid upload flags")
  }
  return {
    batch_id: stringField(value, "batch_id"),
    stored: value.stored,
    idempotent: value.idempotent,
    size: countField(value, "size"),
    checksum: stringField(value, "checksum"),
  }
}

export function isImportApiErrorResponse(value: unknown): value is ImportApiErrorResponse {
  if (!isPlainObject(value) || !exactKeys(value, ["error"]) || !isPlainObject(value.error)) {
    return false
  }
  try {
    parsePublicError(value.error)
    return true
  } catch {
    return false
  }
}

function parsePublicError(value: unknown): ImportPublicError {
  if (!isPlainObject(value) || !exactKeys(value, ["code", "message"])) {
    throw new TypeError("Invalid import error")
  }
  const code = stringField(value, "code")
  const message = stringField(value, "message")
  if (
    code.length > 100 ||
    message.length > 1000 ||
    code !== code.trim() ||
    message !== message.trim() ||
    /[\r\n]/.test(code) ||
    /[\r\n]/.test(message)
  ) {
    throw new TypeError("Invalid import error")
  }
  return { code, message }
}
