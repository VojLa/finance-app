import "server-only"

import { createHash } from "node:crypto"

import type { paths } from "@/generated/python-api"
import {
  contractError,
  forwardedPythonError,
  normalizeAdapterError,
  type SnapshotWorkflowAdapterError,
  unavailableError,
} from "@/modules/python-api/server/errors"
import type { ServerIdentity } from "@/modules/python-api/server/internal-token"
import {
  createAuthenticatedPythonTransport,
  isSafeErrorEnvelope,
  type PythonApiClientOptions,
} from "@/modules/python-api/server/transport"
import type {
  FailedImportFileResult,
  ImportFileResult,
  ImportWorkflowStage,
  PythonImportBatch,
  PythonImportBatchCreateRequest,
  PythonImportCanonicalPostResponse,
  PythonImportClassifyResponse,
  PythonImportDeduplicateResponse,
  PythonImportFinalizeResponse,
  PythonImportNormalizeResponse,
  PythonImportParseResponse,
  PythonImportPostResponse,
  PythonImportSource,
  PythonImportUploadResponse,
} from "./import-contract"
import {
  parseImportBatch,
  parseImportCanonicalPost,
  parseImportClassify,
  parseImportDeduplicate,
  parseImportFinalize,
  parseImportNormalize,
  parseImportParse,
  parseImportPost,
  parseImportUpload,
} from "./import-contract"

type ImportUploadPath = keyof paths & "/api/v1/accounts/{account_id}/imports/{batch_id}/file"

export type ImportWorkflowInput = {
  accountId: string
  source: PythonImportSource
  filename: string
  bytes: Uint8Array
}

export type ImportWorkflowExecution = {
  result: ImportFileResult
  errorStatus?: number
}

function mapImportPythonError(status: number, value: unknown): SnapshotWorkflowAdapterError {
  if ([400, 404, 409, 422].includes(status)) {
    if (!isSafeErrorEnvelope(value)) return contractError()
    return forwardedPythonError(
      status as 400 | 404 | 409 | 422,
      value.error.code,
      value.error.message
    )
  }
  return unavailableError()
}

function requireParsed<T>(parse: (value: unknown) => T, value: unknown): T {
  try {
    return parse(value)
  } catch {
    throw contractError()
  }
}

function requireIdentity(batchId: string, response: { batch_id: string }): void {
  if (response.batch_id !== batchId) throw contractError()
}

function encodePathSegment(value: string): string {
  return encodeURIComponent(value)
}

export function createPythonImportApi(
  identity: ServerIdentity,
  options: PythonApiClientOptions = {}
) {
  const { client, responseData, rawJsonRequest } = createAuthenticatedPythonTransport(
    identity,
    options
  )

  return {
    async createImportBatch(
      accountId: string,
      payload: PythonImportBatchCreateRequest
    ): Promise<PythonImportBatch> {
      const value = await responseData(
        client.POST("/api/v1/accounts/{account_id}/imports", {
          params: { path: { account_id: accountId } },
          body: payload,
        }),
        mapImportPythonError
      )
      return requireParsed(parseImportBatch, value)
    },

    async uploadImportFile(
      accountId: string,
      batchId: string,
      bytes: Uint8Array
    ): Promise<PythonImportUploadResponse> {
      const template: ImportUploadPath = "/api/v1/accounts/{account_id}/imports/{batch_id}/file"
      const path = template
        .replace("{account_id}", encodePathSegment(accountId))
        .replace("{batch_id}", encodePathSegment(batchId))
      const value = await rawJsonRequest<unknown>(
        path,
        {
          method: "PUT",
          headers: { "Content-Type": "application/octet-stream" },
          body: Uint8Array.from(bytes).buffer,
        },
        mapImportPythonError
      )
      return requireParsed(parseImportUpload, value)
    },

    async parseImportBatch(accountId: string, batchId: string): Promise<PythonImportParseResponse> {
      const value = await responseData(
        client.POST("/api/v1/accounts/{account_id}/imports/{batch_id}/parse", {
          params: { path: { account_id: accountId, batch_id: batchId } },
        }),
        mapImportPythonError
      )
      return requireParsed(parseImportParse, value)
    },

    async normalizeImportBatch(
      accountId: string,
      batchId: string
    ): Promise<PythonImportNormalizeResponse> {
      const value = await responseData(
        client.POST("/api/v1/accounts/{account_id}/imports/{batch_id}/normalize", {
          params: { path: { account_id: accountId, batch_id: batchId } },
        }),
        mapImportPythonError
      )
      return requireParsed(parseImportNormalize, value)
    },

    async deduplicateImportBatch(
      accountId: string,
      batchId: string
    ): Promise<PythonImportDeduplicateResponse> {
      const value = await responseData(
        client.POST("/api/v1/accounts/{account_id}/imports/{batch_id}/deduplicate", {
          params: { path: { account_id: accountId, batch_id: batchId } },
        }),
        mapImportPythonError
      )
      return requireParsed(parseImportDeduplicate, value)
    },

    async classifyImportBatch(
      accountId: string,
      batchId: string
    ): Promise<PythonImportClassifyResponse> {
      const value = await responseData(
        client.POST("/api/v1/accounts/{account_id}/imports/{batch_id}/classify", {
          params: { path: { account_id: accountId, batch_id: batchId } },
        }),
        mapImportPythonError
      )
      return requireParsed(parseImportClassify, value)
    },

    async canonicalPostImportBatch(
      accountId: string,
      batchId: string
    ): Promise<PythonImportCanonicalPostResponse> {
      const value = await responseData(
        client.POST("/api/v1/accounts/{account_id}/imports/{batch_id}/canonical-post", {
          params: { path: { account_id: accountId, batch_id: batchId } },
        }),
        mapImportPythonError
      )
      return requireParsed(parseImportCanonicalPost, value)
    },

    async finalizeImportBatches(
      accountId: string,
      batchIds: readonly string[]
    ): Promise<PythonImportFinalizeResponse> {
      const value = await responseData(
        client.POST("/api/v1/accounts/{account_id}/imports/finalize", {
          params: { path: { account_id: accountId } },
          body: { batch_ids: [...batchIds] },
        }),
        mapImportPythonError
      )
      return requireParsed(parseImportFinalize, value)
    },

    async postImportBatch(accountId: string, batchId: string): Promise<PythonImportPostResponse> {
      const value = await responseData(
        client.POST("/api/v1/accounts/{account_id}/imports/{batch_id}/post", {
          params: { path: { account_id: accountId, batch_id: batchId } },
        }),
        mapImportPythonError
      )
      return requireParsed(parseImportPost, value)
    },

    async getImportBatch(accountId: string, batchId: string): Promise<PythonImportBatch> {
      const value = await responseData(
        client.GET("/api/v1/accounts/{account_id}/imports/{batch_id}", {
          params: { path: { account_id: accountId, batch_id: batchId } },
        }),
        mapImportPythonError
      )
      return requireParsed(parseImportBatch, value)
    },
  }
}

export type PythonImportApi = ReturnType<typeof createPythonImportApi>

function failedResult(
  input: ImportWorkflowInput,
  error: SnapshotWorkflowAdapterError,
  state: {
    batchId?: string
    lastSuccessfulStage?: ImportWorkflowStage
    rowsTotal: number
    rowsImported: number
    rowsSkipped: number
    rowsFailed: number
    rowsNeedsReview: number
  }
): ImportWorkflowExecution {
  if (!state.batchId && error.status === 409 && error.code === "import_batch_exists") {
    return {
      result: {
        filename: input.filename,
        status: "duplicate",
        rowsTotal: 0,
        rowsImported: 0,
        rowsSkipped: 0,
        rowsFailed: 0,
        rowsNeedsReview: 0,
        issues: { failed: 0, needsReview: 0 },
        error: { code: error.code, message: error.message },
      },
    }
  }

  const result: FailedImportFileResult = {
    filename: input.filename,
    status: "failed",
    rowsTotal: state.rowsTotal,
    rowsImported: state.rowsImported,
    rowsSkipped: state.rowsSkipped,
    rowsFailed: state.rowsFailed,
    rowsNeedsReview: state.rowsNeedsReview,
    issues: {
      failed: state.rowsFailed,
      needsReview: state.rowsNeedsReview,
    },
    error: { code: error.code, message: error.message },
  }
  if (state.batchId) result.batchId = state.batchId
  if (state.lastSuccessfulStage) result.lastSuccessfulStage = state.lastSuccessfulStage
  return { result, errorStatus: error.status }
}

export async function runImportCanonicalWorkflow(
  identity: ServerIdentity,
  input: ImportWorkflowInput,
  options: PythonApiClientOptions = {}
): Promise<ImportWorkflowExecution> {
  const state: {
    batchId?: string
    lastSuccessfulStage?: ImportWorkflowStage
    rowsTotal: number
    rowsImported: number
    rowsSkipped: number
    rowsFailed: number
    rowsNeedsReview: number
  } = {
    rowsTotal: 0,
    rowsImported: 0,
    rowsSkipped: 0,
    rowsFailed: 0,
    rowsNeedsReview: 0,
  }

  try {
    const checksum = createHash("sha256").update(input.bytes).digest("hex")
    const api = createPythonImportApi(identity, options)
    const batch = await api.createImportBatch(input.accountId, {
      source: input.source,
      filename: input.filename,
      file_size: input.bytes.byteLength,
      file_encoding: null,
      checksum,
    })
    if (
      batch.account_id !== input.accountId ||
      batch.source !== input.source ||
      batch.filename !== input.filename ||
      batch.file_size !== input.bytes.byteLength ||
      batch.checksum !== checksum
    ) {
      throw contractError()
    }
    state.batchId = batch.id
    state.lastSuccessfulStage = "created"

    const upload = await api.uploadImportFile(input.accountId, batch.id, input.bytes)
    requireIdentity(batch.id, upload)
    if (upload.size !== input.bytes.byteLength || upload.checksum !== checksum) {
      throw contractError()
    }
    state.lastSuccessfulStage = "uploaded"

    const parsed = await api.parseImportBatch(input.accountId, batch.id)
    requireIdentity(batch.id, parsed)
    state.lastSuccessfulStage = "parsed"
    state.rowsTotal = parsed.rows_total
    state.rowsFailed = parsed.rows_failed

    const normalized = await api.normalizeImportBatch(input.accountId, batch.id)
    requireIdentity(batch.id, normalized)
    state.lastSuccessfulStage = "normalized"
    state.rowsTotal = normalized.rows_total
    state.rowsFailed = normalized.rows_failed
    state.rowsNeedsReview = normalized.rows_needs_review

    const deduplicated = await api.deduplicateImportBatch(input.accountId, batch.id)
    requireIdentity(batch.id, deduplicated)
    state.lastSuccessfulStage = "deduplicated"
    state.rowsTotal = deduplicated.rows_total
    state.rowsSkipped = deduplicated.rows_duplicate
    state.rowsFailed = deduplicated.rows_failed
    state.rowsNeedsReview = deduplicated.rows_needs_review

    const classified = await api.classifyImportBatch(input.accountId, batch.id)
    requireIdentity(batch.id, classified)
    state.lastSuccessfulStage = "classified"
    state.rowsTotal = classified.rows_total
    state.rowsSkipped = classified.rows_duplicate + classified.rows_skipped
    state.rowsFailed = classified.rows_failed
    state.rowsNeedsReview = classified.rows_needs_review

    const posted = await api.canonicalPostImportBatch(input.accountId, batch.id)
    requireIdentity(batch.id, posted)
    state.lastSuccessfulStage = "posted"
    state.rowsTotal = posted.rows_total
    state.rowsImported = posted.rows_imported
    state.rowsSkipped = posted.rows_skipped

    const finalBatch = await api.getImportBatch(input.accountId, batch.id)
    if (
      finalBatch.id !== batch.id ||
      finalBatch.account_id !== input.accountId ||
      finalBatch.source !== input.source ||
      finalBatch.filename !== input.filename ||
      finalBatch.rows_total !== posted.rows_total ||
      finalBatch.rows_imported !== posted.rows_imported ||
      finalBatch.rows_skipped !== posted.rows_skipped ||
      !["completed", "partially_completed"].includes(finalBatch.status)
    ) {
      throw contractError()
    }

    return {
      result: {
        filename: input.filename,
        batchId: batch.id,
        status: finalBatch.status as "completed" | "partially_completed",
        lastSuccessfulStage: "status",
        rowsTotal: posted.rows_total,
        rowsImported: posted.rows_imported,
        rowsSkipped: posted.rows_skipped,
        rowsFailed: state.rowsFailed,
        rowsNeedsReview: state.rowsNeedsReview,
        issues: {
          failed: state.rowsFailed,
          needsReview: state.rowsNeedsReview,
        },
      },
    }
  } catch (error) {
    return failedResult(input, normalizeAdapterError(error), state)
  }
}
