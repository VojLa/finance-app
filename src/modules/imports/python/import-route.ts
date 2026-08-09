import "server-only"

import { getServerSession } from "next-auth"
import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

import { authOptions } from "@/lib/auth"
import {
  contractError,
  normalizeAdapterError,
  toErrorResponse,
  validationError,
} from "@/modules/python-api/server/errors"
import {
  isPythonImportSource,
  summarizeImportFiles,
  withImportFinalization,
  type ImportApiErrorResponse,
  type ImportFinalizationRequest,
  type ImportFinalizationResult,
  type PythonImportSource,
} from "./import-contract"
import { createPythonImportApi, runImportCanonicalWorkflow } from "./import-api"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }
const MAX_FILES = 10
const MAX_FILE_SIZE = 64 * 1024 * 1024

function authenticationRequired() {
  return NextResponse.json(
    {
      error: {
        code: "authentication_required",
        message: "Authentication is required.",
      },
    },
    { status: 401, headers: NO_STORE_HEADERS }
  )
}

function safeAdapterResponse(error: unknown) {
  const mapped = toErrorResponse(normalizeAdapterError(error))
  return NextResponse.json(mapped.body, {
    status: mapped.status,
    headers: NO_STORE_HEADERS,
  })
}

function exactFormKeys(formData: FormData, fixedSource?: PythonImportSource): boolean {
  const allowed = new Set(fixedSource ? ["accountId", "file"] : ["accountId", "source", "file"])
  return [...formData.keys()].every((key) => allowed.has(key))
}

function parseAccountId(formData: FormData): string {
  const values = formData.getAll("accountId")
  const value = values[0]
  if (
    values.length !== 1 ||
    typeof value !== "string" ||
    value.length === 0 ||
    value !== value.trim()
  ) {
    throw validationError()
  }
  return value
}

function parseSource(formData: FormData, fixedSource?: PythonImportSource): PythonImportSource {
  if (fixedSource) return fixedSource
  const values = formData.getAll("source")
  if (values.length !== 1 || !isPythonImportSource(values[0])) {
    throw validationError()
  }
  return values[0]
}

function parseFiles(formData: FormData): File[] {
  const files = formData.getAll("file").filter((value): value is File => value instanceof File)
  if (
    files.length === 0 ||
    files.length > MAX_FILES ||
    files.length !== formData.getAll("file").length
  ) {
    throw validationError()
  }
  for (const file of files) {
    if (
      file.name.length === 0 ||
      !file.name.toLowerCase().endsWith(".csv") ||
      file.size === 0 ||
      file.size > MAX_FILE_SIZE
    ) {
      throw validationError()
    }
  }
  return files
}

function parseFinalizationRequest(value: unknown): ImportFinalizationRequest {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  ) {
    throw validationError()
  }
  const record = value as Record<string, unknown>
  if (
    Object.keys(record).length !== 2 ||
    !Object.hasOwn(record, "accountId") ||
    !Object.hasOwn(record, "batchIds") ||
    typeof record.accountId !== "string" ||
    record.accountId.length === 0 ||
    record.accountId !== record.accountId.trim() ||
    !Array.isArray(record.batchIds) ||
    record.batchIds.length === 0 ||
    record.batchIds.length > MAX_FILES ||
    record.batchIds.some(
      (batchId) => typeof batchId !== "string" || batchId.length === 0 || batchId !== batchId.trim()
    ) ||
    new Set(record.batchIds).size !== record.batchIds.length
  ) {
    throw validationError()
  }
  return {
    accountId: record.accountId,
    batchIds: record.batchIds,
  }
}

export async function handleImportPost(request: NextRequest, fixedSource?: PythonImportSource) {
  const session = await getServerSession(authOptions)
  if (!session?.user || session.user.id.trim().length === 0) {
    return authenticationRequired()
  }

  try {
    let formData: FormData
    try {
      formData = await request.formData()
    } catch {
      throw validationError()
    }
    if (!exactFormKeys(formData, fixedSource)) throw validationError()

    const accountId = parseAccountId(formData)
    const source = parseSource(formData, fixedSource)
    const files = parseFiles(formData)
    const identity = {
      userId: session.user.id,
      email: session.user.email || undefined,
    }

    const executions = []
    for (const file of files) {
      const bytes = new Uint8Array(await file.arrayBuffer())
      executions.push(
        await runImportCanonicalWorkflow(identity, {
          accountId,
          source,
          filename: file.name,
          bytes,
        })
      )
    }
    const summary = summarizeImportFiles(executions.map((execution) => execution.result))
    const failed = executions.find((execution) => execution.errorStatus !== undefined)
    if (failed) {
      const result = failed.result
      const error =
        "error" in result
          ? result.error
          : {
              code: "python_api_contract_error",
              message: "The Python API returned an incompatible response.",
            }
      const body: ImportApiErrorResponse = {
        error,
        partial: withImportFinalization(summary, "not_run"),
      }
      return NextResponse.json(body, {
        status: failed.errorStatus,
        headers: NO_STORE_HEADERS,
      })
    }
    const batchIds = executions.flatMap((execution) =>
      "batchId" in execution.result && execution.result.status !== "failed"
        ? [execution.result.batchId]
        : []
    )
    const expectedBatchIds = [...batchIds].sort()
    let finalized
    try {
      finalized = await createPythonImportApi(identity).finalizeImportBatches(accountId, batchIds)
    } catch (error) {
      const mapped = toErrorResponse(normalizeAdapterError(error))
      const body: ImportApiErrorResponse = {
        error: mapped.body.error,
        partial: withImportFinalization(summary, "not_run"),
      }
      return NextResponse.json(body, {
        status: mapped.status,
        headers: NO_STORE_HEADERS,
      })
    }
    if (
      finalized.batch_ids.length !== expectedBatchIds.length ||
      finalized.batch_ids.some((batchId, index) => batchId !== expectedBatchIds[index])
    ) {
      throw contractError()
    }
    return NextResponse.json(withImportFinalization(summary, finalized.snapshot_refresh_status), {
      headers: NO_STORE_HEADERS,
    })
  } catch (error) {
    return safeAdapterResponse(error)
  }
}

export async function handleImportFinalize(request: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user || session.user.id.trim().length === 0) {
    return authenticationRequired()
  }
  try {
    let value: unknown
    try {
      value = await request.json()
    } catch {
      throw validationError()
    }
    const input = parseFinalizationRequest(value)
    const expectedBatchIds = [...input.batchIds].sort()
    const finalized = await createPythonImportApi({
      userId: session.user.id,
      email: session.user.email || undefined,
    }).finalizeImportBatches(input.accountId, input.batchIds)
    if (
      finalized.batch_ids.length !== expectedBatchIds.length ||
      finalized.batch_ids.some((batchId, index) => batchId !== expectedBatchIds[index])
    ) {
      throw contractError()
    }
    return NextResponse.json(
      {
        batchIds: finalized.batch_ids,
        snapshotRefreshStatus: finalized.snapshot_refresh_status,
      } satisfies ImportFinalizationResult,
      { headers: NO_STORE_HEADERS }
    )
  } catch (error) {
    return safeAdapterResponse(error)
  }
}
