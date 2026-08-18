import type { ImportJobAcceptance, PythonImportJob, PythonImportSource } from "./import-contract"
import { isImportApiErrorResponse, parseImportJob } from "./import-contract"

export const IMPORT_PATH = "/api/import"

type FetchImplementation = typeof fetch

export class ImportClientError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string
  ) {
    super(message)
    this.name = "ImportClientError"
  }
}

function parseJob(value: unknown): PythonImportJob {
  try {
    return parseImportJob(value)
  } catch {
    throw new ImportClientError(
      502,
      "python_api_contract_error",
      "Import API returned invalid data."
    )
  }
}

function parseAcceptance(value: unknown): ImportJobAcceptance {
  if (typeof value !== "object" || value === null || !Object.hasOwn(value, "job")) {
    throw new ImportClientError(
      502,
      "python_api_contract_error",
      "Import API returned invalid data."
    )
  }
  const record = value as Record<string, unknown>
  if (
    Object.keys(record).sort().join("|") !== "acceptedBatchIds|job|outcome|rejectedFiles" ||
    !["started", "resumed"].includes(record.outcome as string) ||
    !Array.isArray(record.acceptedBatchIds) ||
    (record.outcome === "started" && record.acceptedBatchIds.length < 1) ||
    record.acceptedBatchIds.length > 10 ||
    !Array.isArray(record.rejectedFiles) ||
    record.acceptedBatchIds.some(
      (item, index, batchIds) =>
        typeof item !== "string" ||
        !item ||
        item.length > 255 ||
        item !== item.trim() ||
        (index > 0 && item <= batchIds[index - 1])
    ) ||
    record.acceptedBatchIds.length + record.rejectedFiles.length > 10 ||
    record.rejectedFiles.some(
      (item) =>
        typeof item !== "object" ||
        item === null ||
        Object.keys(item).sort().join("|") !== "code|filename|message" ||
        ["filename", "code", "message"].some((field) => {
          const value = (item as Record<string, unknown>)[field]
          const maximum = field === "filename" ? 255 : field === "code" ? 100 : 1000
          return (
            typeof value !== "string" ||
            !value ||
            value.length > maximum ||
            value !== value.trim() ||
            /[\r\n]/.test(value)
          )
        })
    )
  ) {
    throw new ImportClientError(
      502,
      "python_api_contract_error",
      "Import API returned invalid data."
    )
  }
  const job = parseJob(record.job)
  const outcome = record.outcome as ImportJobAcceptance["outcome"]
  if (
    (outcome === "started" && job.progress.total_batches !== record.acceptedBatchIds.length) ||
    (outcome === "resumed" && record.acceptedBatchIds.length !== 0)
  ) {
    throw new ImportClientError(
      502,
      "python_api_contract_error",
      "Import API returned invalid data."
    )
  }
  return {
    outcome,
    job,
    acceptedBatchIds: record.acceptedBatchIds,
    rejectedFiles: record.rejectedFiles as ImportJobAcceptance["rejectedFiles"],
  }
}

async function json(response: Response): Promise<unknown> {
  if (!response.headers.get("content-type")?.toLowerCase().includes("json")) {
    throw new ImportClientError(502, "python_api_unavailable", "Import API is unavailable.")
  }
  return response.json()
}

async function requestJob(
  path: string,
  init: RequestInit,
  fetchImplementation: FetchImplementation
): Promise<PythonImportJob> {
  try {
    const response = await fetchImplementation(path, { ...init, cache: "no-store" })
    const value = await json(response)
    if (!response.ok) {
      if (!isImportApiErrorResponse(value)) {
        throw new ImportClientError(502, "python_api_unavailable", "Import API is unavailable.")
      }
      throw new ImportClientError(response.status, value.error.code, value.error.message)
    }
    if (response.status !== 200) {
      throw new ImportClientError(
        502,
        "python_api_contract_error",
        "Import API returned invalid data."
      )
    }
    return parseJob(value)
  } catch (error) {
    if (error instanceof ImportClientError) throw error
    throw new ImportClientError(502, "python_api_unavailable", "Import API is unavailable.")
  }
}

export async function requestImport(
  accountId: string,
  source: PythonImportSource,
  files: readonly File[],
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<ImportJobAcceptance> {
  const formData = new FormData()
  formData.append("accountId", accountId)
  formData.append("source", source)
  files.forEach((file) => formData.append("file", file))
  try {
    const response = await fetchImplementation(IMPORT_PATH, {
      method: "POST",
      body: formData,
      cache: "no-store",
    })
    const value = await json(response)
    if (!response.ok) {
      if (isImportApiErrorResponse(value)) {
        throw new ImportClientError(response.status, value.error.code, value.error.message)
      }
      throw new ImportClientError(502, "python_api_unavailable", "Import API is unavailable.")
    }
    if (response.status !== 202) {
      throw new ImportClientError(
        502,
        "python_api_contract_error",
        "Import API returned invalid data."
      )
    }
    const acceptance = parseAcceptance(value)
    if (acceptance.job.account_id !== accountId) {
      throw new ImportClientError(
        502,
        "python_api_contract_error",
        "Import API returned invalid data."
      )
    }
    return acceptance
  } catch (error) {
    if (error instanceof ImportClientError) throw error
    throw new ImportClientError(502, "python_api_unavailable", "Import API is unavailable.")
  }
}

export async function requestImportJob(
  accountId: string,
  jobId: string,
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<PythonImportJob> {
  const job = await requestJob(
    `/api/import/jobs/${encodeURIComponent(jobId)}?accountId=${encodeURIComponent(accountId)}`,
    { method: "GET" },
    fetchImplementation
  )
  if (job.account_id !== accountId || job.id !== jobId) {
    throw new ImportClientError(
      502,
      "python_api_contract_error",
      "Import API returned invalid data."
    )
  }
  return job
}

export async function retryImportJob(
  accountId: string,
  jobId: string,
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<PythonImportJob> {
  const job = await requestJob(
    `/api/import/jobs/${encodeURIComponent(jobId)}/retry`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accountId }),
    },
    fetchImplementation
  )
  if (job.account_id !== accountId || job.id !== jobId) {
    throw new ImportClientError(
      502,
      "python_api_contract_error",
      "Import API returned invalid data."
    )
  }
  return job
}
