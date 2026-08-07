import type { components } from "@/generated/python-api"

export type PythonImportBatchCreateRequest = components["schemas"]["ImportBatchCreateRequest"]
export type PythonImportBatch = components["schemas"]["ImportBatchResponse"]
export type PythonImportUploadResponse = components["schemas"]["ImportUploadResponse"]
export type PythonImportParseResponse = components["schemas"]["ImportParseResponse"]
export type PythonImportNormalizeResponse = components["schemas"]["ImportNormalizeResponse"]
export type PythonImportDeduplicateResponse = components["schemas"]["ImportDeduplicateResponse"]
export type PythonImportClassifyResponse = components["schemas"]["ImportClassifyResponse"]
export type PythonImportCanonicalPostResponse = components["schemas"]["ImportCanonicalPostResponse"]
export type PythonImportFinalizeRequest = components["schemas"]["FinalizeImportBatchesRequest"]
export type PythonImportFinalizeResponse = components["schemas"]["FinalizeImportBatchesResponse"]
export type PythonImportPostResponse = components["schemas"]["ImportPostResponse"]
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

export type ImportWorkflowStage =
  | "created"
  | "uploaded"
  | "parsed"
  | "normalized"
  | "deduplicated"
  | "classified"
  | "posted"
  | "status"

export type ImportPublicError = {
  code: string
  message: string
}

type ImportFileCounts = {
  rowsTotal: number
  rowsImported: number
  rowsSkipped: number
  rowsFailed: number
  rowsNeedsReview: number
}

export type CompletedImportFileResult = ImportFileCounts & {
  filename: string
  batchId: string
  status: "completed" | "partially_completed"
  lastSuccessfulStage: "status"
  issues: {
    failed: number
    needsReview: number
  }
}

export type DuplicateImportFileResult = ImportFileCounts & {
  filename: string
  status: "duplicate"
  lastSuccessfulStage?: never
  error: ImportPublicError
  issues: {
    failed: 0
    needsReview: 0
  }
}

export type FailedImportFileResult = ImportFileCounts & {
  filename: string
  batchId?: string
  status: "failed"
  lastSuccessfulStage?: ImportWorkflowStage
  error: ImportPublicError
  issues: {
    failed: number
    needsReview: number
  }
}

export type ImportFileResult =
  | CompletedImportFileResult
  | DuplicateImportFileResult
  | FailedImportFileResult

export type ImportFinalizationStatus =
  | PythonImportFinalizeResponse["snapshot_refresh_status"]
  | "not_run"

export type ImportFilesSummary = {
  files: ImportFileResult[]
  rowsTotal: number
  rowsImported: number
  rowsSkipped: number
  rowsFailed: number
  rowsNeedsReview: number
  completedFiles: number
  duplicateFiles: number
  failedFiles: number
}

export type ImportSummary = ImportFilesSummary & {
  snapshotRefreshStatus: ImportFinalizationStatus
}

export type ImportFinalizationRequest = {
  accountId: string
  batchIds: string[]
}

export type ImportFinalizationResult = {
  batchIds: string[]
  snapshotRefreshStatus: PythonImportFinalizeResponse["snapshot_refresh_status"]
}

export type ImportApiErrorResponse = {
  error: ImportPublicError
  partial?: ImportSummary
}

export type ImportStatusResult = {
  batches: Array<{
    id: string
    accountId: string
    source: PythonImportSource
    filename: string
    status: PythonImportStatus
    rowsTotal: number
    rowsImported: number
    rowsSkipped: number
  }>
}

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
  if (!Number.isInteger(field) || (field as number) < 0) {
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

function parseStageBase(
  value: unknown,
  countNames: readonly string[]
): Record<string, string | number> {
  if (!isPlainObject(value)) throw new TypeError("Invalid import stage response")
  const result: Record<string, string | number> = {
    batch_id: stringField(value, "batch_id"),
    status: importStatus(value.status),
  }
  for (const name of countNames) result[name] = countField(value, name)
  return result
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

export function parseImportParse(value: unknown): PythonImportParseResponse {
  return parseStageBase(value, [
    "rows_total",
    "rows_pending",
    "rows_failed",
  ]) as PythonImportParseResponse
}

export function parseImportNormalize(value: unknown): PythonImportNormalizeResponse {
  return parseStageBase(value, [
    "rows_total",
    "rows_normalized",
    "rows_needs_review",
    "rows_failed",
  ]) as PythonImportNormalizeResponse
}

export function parseImportDeduplicate(value: unknown): PythonImportDeduplicateResponse {
  return parseStageBase(value, [
    "rows_total",
    "rows_unique",
    "rows_duplicate",
    "rows_needs_review",
    "rows_failed",
  ]) as PythonImportDeduplicateResponse
}

export function parseImportClassify(value: unknown): PythonImportClassifyResponse {
  return parseStageBase(value, [
    "rows_total",
    "rows_classified",
    "rows_duplicate",
    "rows_needs_review",
    "rows_failed",
    "rows_skipped",
  ]) as PythonImportClassifyResponse
}

export function parseImportPost(value: unknown): PythonImportPostResponse {
  if (!isPlainObject(value)) throw new TypeError("Invalid post response")
  const completedAt = stringField(value, "completed_at")
  if (Number.isNaN(Date.parse(completedAt)) || typeof value.replayed !== "boolean") {
    throw new TypeError("Invalid post response")
  }
  const refreshStatuses = [
    "created",
    "replayed",
    "not_required",
    "unavailable",
    "conflict",
  ] as const
  if (
    typeof value.snapshot_refresh_status !== "string" ||
    !refreshStatuses.includes(
      value.snapshot_refresh_status as PythonImportPostResponse["snapshot_refresh_status"]
    )
  ) {
    throw new TypeError("Invalid snapshot refresh status")
  }
  return {
    batch_id: stringField(value, "batch_id"),
    status: importStatus(value.status),
    rows_total: countField(value, "rows_total"),
    rows_imported: countField(value, "rows_imported"),
    rows_skipped: countField(value, "rows_skipped"),
    replayed: value.replayed,
    completed_at: completedAt,
    snapshot_refresh_status:
      value.snapshot_refresh_status as PythonImportPostResponse["snapshot_refresh_status"],
  }
}

export function parseImportCanonicalPost(value: unknown): PythonImportCanonicalPostResponse {
  if (!isPlainObject(value)) throw new TypeError("Invalid canonical post response")
  const completedAt = stringField(value, "completed_at")
  if (Number.isNaN(Date.parse(completedAt)) || typeof value.replayed !== "boolean") {
    throw new TypeError("Invalid canonical post response")
  }
  return {
    batch_id: stringField(value, "batch_id"),
    status: importStatus(value.status),
    rows_total: countField(value, "rows_total"),
    rows_imported: countField(value, "rows_imported"),
    rows_skipped: countField(value, "rows_skipped"),
    completed_at: completedAt,
    replayed: value.replayed,
  }
}

const SNAPSHOT_REFRESH_STATUSES = [
  "created",
  "replayed",
  "not_required",
  "unavailable",
  "conflict",
] as const satisfies readonly PythonImportFinalizeResponse["snapshot_refresh_status"][]

export function parseImportFinalize(value: unknown): PythonImportFinalizeResponse {
  if (
    !isPlainObject(value) ||
    !Array.isArray(value.batch_ids) ||
    value.batch_ids.some(
      (batchId) => typeof batchId !== "string" || batchId.length === 0 || batchId.trim() !== batchId
    ) ||
    new Set(value.batch_ids).size !== value.batch_ids.length ||
    typeof value.snapshot_refresh_status !== "string" ||
    !SNAPSHOT_REFRESH_STATUSES.includes(
      value.snapshot_refresh_status as PythonImportFinalizeResponse["snapshot_refresh_status"]
    )
  ) {
    throw new TypeError("Invalid import finalization response")
  }
  return {
    batch_ids: value.batch_ids,
    snapshot_refresh_status:
      value.snapshot_refresh_status as PythonImportFinalizeResponse["snapshot_refresh_status"],
  }
}

export function summarizeImportFiles(files: readonly ImportFileResult[]): ImportFilesSummary {
  return files.reduce<ImportFilesSummary>(
    (summary, file) => ({
      files: [...summary.files, file],
      rowsTotal: summary.rowsTotal + file.rowsTotal,
      rowsImported: summary.rowsImported + file.rowsImported,
      rowsSkipped: summary.rowsSkipped + file.rowsSkipped,
      rowsFailed: summary.rowsFailed + file.rowsFailed,
      rowsNeedsReview: summary.rowsNeedsReview + file.rowsNeedsReview,
      completedFiles:
        summary.completedFiles +
        (file.status === "completed" || file.status === "partially_completed" ? 1 : 0),
      duplicateFiles: summary.duplicateFiles + (file.status === "duplicate" ? 1 : 0),
      failedFiles: summary.failedFiles + (file.status === "failed" ? 1 : 0),
    }),
    {
      files: [],
      rowsTotal: 0,
      rowsImported: 0,
      rowsSkipped: 0,
      rowsFailed: 0,
      rowsNeedsReview: 0,
      completedFiles: 0,
      duplicateFiles: 0,
      failedFiles: 0,
    }
  )
}

export function withImportFinalization(
  summary: ImportFilesSummary,
  snapshotRefreshStatus: ImportFinalizationStatus
): ImportSummary {
  return { ...summary, snapshotRefreshStatus }
}

export function recoverableBatchIds(summary: ImportSummary): string[] {
  return summary.files
    .flatMap((file) => {
      if (file.status === "completed" || file.status === "partially_completed") {
        return [file.batchId]
      }
      if (
        file.status === "failed" &&
        file.lastSuccessfulStage === "posted" &&
        file.batchId !== undefined
      ) {
        return [file.batchId]
      }
      return []
    })
    .sort()
}

export function requiresImportFinalizationRecovery(summary: ImportSummary): boolean {
  return (
    recoverableBatchIds(summary).length > 0 &&
    ["not_run", "unavailable", "conflict"].includes(summary.snapshotRefreshStatus)
  )
}

export function parseImportFinalizationResult(value: unknown): ImportFinalizationResult {
  if (
    !isPlainObject(value) ||
    Object.keys(value).length !== 2 ||
    !Object.hasOwn(value, "batchIds") ||
    !Object.hasOwn(value, "snapshotRefreshStatus") ||
    !Array.isArray(value.batchIds)
  ) {
    throw new TypeError("Invalid import finalization result")
  }
  const batchIds = value.batchIds
  const snapshotRefreshStatus = value.snapshotRefreshStatus
  if (
    batchIds.length === 0 ||
    batchIds.length > 10 ||
    batchIds.some(
      (batchId) => typeof batchId !== "string" || batchId.length === 0 || batchId.trim() !== batchId
    ) ||
    new Set(batchIds).size !== batchIds.length ||
    batchIds.some((batchId, index) => index > 0 && batchId < batchIds[index - 1]) ||
    typeof snapshotRefreshStatus !== "string" ||
    !SNAPSHOT_REFRESH_STATUSES.includes(
      snapshotRefreshStatus as PythonImportFinalizeResponse["snapshot_refresh_status"]
    )
  ) {
    throw new TypeError("Invalid import finalization result")
  }
  return {
    batchIds,
    snapshotRefreshStatus:
      snapshotRefreshStatus as PythonImportFinalizeResponse["snapshot_refresh_status"],
  }
}

export function isImportApiErrorResponse(value: unknown): value is ImportApiErrorResponse {
  if (!isPlainObject(value) || !isPlainObject(value.error)) return false
  return (
    typeof value.error.code === "string" &&
    value.error.code.length > 0 &&
    typeof value.error.message === "string" &&
    value.error.message.length > 0
  )
}

function parsePublicError(value: unknown): ImportPublicError {
  if (!isPlainObject(value)) throw new TypeError("Invalid import error")
  return {
    code: stringField(value, "code"),
    message: stringField(value, "message"),
  }
}

export function parseImportFileResult(value: unknown): ImportFileResult {
  if (!isPlainObject(value) || !isPlainObject(value.issues)) {
    throw new TypeError("Invalid import file result")
  }
  const filename = stringField(value, "filename")
  const status = stringField(value, "status")
  const counts = {
    rowsTotal: countField(value, "rowsTotal"),
    rowsImported: countField(value, "rowsImported"),
    rowsSkipped: countField(value, "rowsSkipped"),
    rowsFailed: countField(value, "rowsFailed"),
    rowsNeedsReview: countField(value, "rowsNeedsReview"),
  }
  const issues = {
    failed: countField(value.issues, "failed"),
    needsReview: countField(value.issues, "needsReview"),
  }
  if (issues.failed !== counts.rowsFailed || issues.needsReview !== counts.rowsNeedsReview) {
    throw new TypeError("Invalid issue counts")
  }
  if (status === "duplicate") {
    return {
      filename,
      status,
      ...counts,
      issues: { failed: 0, needsReview: 0 },
      error: parsePublicError(value.error),
    }
  }
  if (status === "failed") {
    const batchId = value.batchId === undefined ? undefined : stringField(value, "batchId")
    const lastSuccessfulStage =
      value.lastSuccessfulStage === undefined
        ? undefined
        : stringField(value, "lastSuccessfulStage")
    const stages: readonly ImportWorkflowStage[] = [
      "created",
      "uploaded",
      "parsed",
      "normalized",
      "deduplicated",
      "classified",
      "posted",
      "status",
    ]
    if (
      lastSuccessfulStage !== undefined &&
      !stages.includes(lastSuccessfulStage as ImportWorkflowStage)
    ) {
      throw new TypeError("Invalid workflow stage")
    }
    return {
      filename,
      status,
      ...counts,
      issues,
      error: parsePublicError(value.error),
      ...(batchId ? { batchId } : {}),
      ...(lastSuccessfulStage
        ? { lastSuccessfulStage: lastSuccessfulStage as ImportWorkflowStage }
        : {}),
    }
  }
  if (status !== "completed" && status !== "partially_completed") {
    throw new TypeError("Invalid import file status")
  }
  return {
    filename,
    batchId: stringField(value, "batchId"),
    status,
    lastSuccessfulStage: "status",
    ...counts,
    issues,
  }
}

export function parseImportSummary(value: unknown): ImportSummary {
  if (!isPlainObject(value) || !Array.isArray(value.files)) {
    throw new TypeError("Invalid import summary")
  }
  const files = value.files.map(parseImportFileResult)
  const projected = summarizeImportFiles(files)
  for (const key of [
    "rowsTotal",
    "rowsImported",
    "rowsSkipped",
    "rowsFailed",
    "rowsNeedsReview",
    "completedFiles",
    "duplicateFiles",
    "failedFiles",
  ] as const) {
    if (countField(value, key) !== projected[key]) {
      throw new TypeError(`Invalid ${key}`)
    }
  }
  const finalizationStatus = stringField(value, "snapshotRefreshStatus")
  if (
    finalizationStatus !== "not_run" &&
    !SNAPSHOT_REFRESH_STATUSES.includes(
      finalizationStatus as PythonImportFinalizeResponse["snapshot_refresh_status"]
    )
  ) {
    throw new TypeError("Invalid snapshotRefreshStatus")
  }
  return withImportFinalization(projected, finalizationStatus as ImportFinalizationStatus)
}
