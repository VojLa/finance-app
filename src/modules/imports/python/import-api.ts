import "server-only"

import type { paths } from "@/generated/python-api"
import {
  contractError,
  forwardedPythonError,
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
  PythonImportBatch,
  PythonImportBatchCreateRequest,
  PythonImportJob,
  PythonImportUploadResponse,
} from "./import-contract"
import { parseImportBatch, parseImportJob, parseImportUpload } from "./import-contract"

type ImportUploadPath = keyof paths & "/api/v1/accounts/{account_id}/imports/{batch_id}/file"

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

function encodePathSegment(value: string): string {
  return encodeURIComponent(value)
}

/** Thin server-only transport for durable Python import jobs. */
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

    async startImportJob(accountId: string, batchIds: readonly string[]): Promise<PythonImportJob> {
      const value = await responseData(
        client.POST("/api/v1/accounts/{account_id}/imports/jobs", {
          params: { path: { account_id: accountId } },
          body: { batch_ids: [...batchIds] },
        }),
        mapImportPythonError
      )
      return requireParsed(parseImportJob, value)
    },

    async getImportJob(accountId: string, jobId: string): Promise<PythonImportJob> {
      const value = await responseData(
        client.GET("/api/v1/accounts/{account_id}/imports/jobs/{job_id}", {
          params: { path: { account_id: accountId, job_id: jobId } },
        }),
        mapImportPythonError
      )
      return requireParsed(parseImportJob, value)
    },

    async retryImportJob(accountId: string, jobId: string): Promise<PythonImportJob> {
      const value = await responseData(
        client.POST("/api/v1/accounts/{account_id}/imports/jobs/{job_id}/retry", {
          params: { path: { account_id: accountId, job_id: jobId } },
        }),
        mapImportPythonError
      )
      return requireParsed(parseImportJob, value)
    },
  }
}

export type PythonImportApi = ReturnType<typeof createPythonImportApi>
