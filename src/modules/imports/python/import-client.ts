import type {
  ImportApiErrorResponse,
  ImportFinalizationResult,
  ImportSummary,
  PythonImportSource,
} from "./import-contract"
import {
  isImportApiErrorResponse,
  parseImportFinalizationResult,
  parseImportSummary,
} from "./import-contract"

export const IMPORT_PATH = "/api/import"
export const IMPORT_FINALIZE_PATH = "/api/import/finalize"

type FetchImplementation = typeof fetch

export class ImportClientError extends Error {
  readonly status: number
  readonly code: string
  readonly partial?: ImportSummary

  constructor(status: number, code: string, message: string, partial?: ImportSummary) {
    super(message)
    this.name = "ImportClientError"
    this.status = status
    this.code = code
    this.partial = partial
  }
}

function unavailableError(): ImportClientError {
  return new ImportClientError(502, "python_api_unavailable", "Import API není dostupné.")
}

function contractError(): ImportClientError {
  return new ImportClientError(
    502,
    "python_api_contract_error",
    "Import API vrátilo nekompatibilní odpověď."
  )
}

export async function requestImport(
  accountId: string,
  source: PythonImportSource,
  files: readonly File[],
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<ImportSummary> {
  const formData = new FormData()
  formData.append("accountId", accountId)
  formData.append("source", source)
  for (const file of files) formData.append("file", file)

  try {
    const response = await fetchImplementation(IMPORT_PATH, {
      method: "POST",
      body: formData,
      cache: "no-store",
    })
    if (!response.headers.get("content-type")?.toLowerCase().includes("json")) {
      throw unavailableError()
    }
    const value: unknown = await response.json()
    if (!response.ok) {
      if (!isImportApiErrorResponse(value)) throw unavailableError()
      let partial: ImportSummary | undefined
      if ("partial" in value && value.partial !== undefined) {
        try {
          partial = parseImportSummary(value.partial)
        } catch {
          throw contractError()
        }
      }
      throw new ImportClientError(response.status, value.error.code, value.error.message, partial)
    }
    try {
      return parseImportSummary(value)
    } catch {
      throw contractError()
    }
  } catch (error) {
    if (error instanceof ImportClientError) throw error
    throw unavailableError()
  }
}

export async function requestImportFinalization(
  accountId: string,
  batchIds: readonly string[],
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<ImportFinalizationResult> {
  try {
    const response = await fetchImplementation(IMPORT_FINALIZE_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accountId, batchIds }),
      cache: "no-store",
    })
    if (!response.headers.get("content-type")?.toLowerCase().includes("json")) {
      throw unavailableError()
    }
    const value: unknown = await response.json()
    if (!response.ok) {
      if (!isImportApiErrorResponse(value)) throw unavailableError()
      throw new ImportClientError(response.status, value.error.code, value.error.message)
    }
    try {
      return parseImportFinalizationResult(value)
    } catch {
      throw contractError()
    }
  } catch (error) {
    if (error instanceof ImportClientError) throw error
    throw unavailableError()
  }
}

export function toImportErrorResponse(error: ImportClientError): ImportApiErrorResponse {
  return {
    error: { code: error.code, message: error.message },
    ...(error.partial ? { partial: error.partial } : {}),
  }
}
