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
  type ImportApiErrorResponse,
  type ImportStatusResult,
  type PythonImportSource,
} from "./import-contract"
import { createPythonImportApi, runImportWorkflow } from "./import-api"

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
        await runImportWorkflow(identity, {
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
      const body: ImportApiErrorResponse = { error, partial: summary }
      return NextResponse.json(body, {
        status: failed.errorStatus,
        headers: NO_STORE_HEADERS,
      })
    }
    return NextResponse.json(summary, { headers: NO_STORE_HEADERS })
  } catch (error) {
    return safeAdapterResponse(error)
  }
}

function parseStatusQuery(request: NextRequest): { accountId: string; ids: string[] } {
  const allowed = new Set(["accountId", "ids"])
  if ([...request.nextUrl.searchParams.keys()].some((key) => !allowed.has(key))) {
    throw validationError()
  }
  const accountId = request.nextUrl.searchParams.get("accountId")
  const rawIds = request.nextUrl.searchParams.get("ids")
  if (
    !accountId ||
    accountId !== accountId.trim() ||
    !rawIds ||
    request.nextUrl.searchParams.getAll("accountId").length !== 1 ||
    request.nextUrl.searchParams.getAll("ids").length !== 1
  ) {
    throw validationError()
  }
  const ids = rawIds.split(",")
  if (
    ids.length === 0 ||
    ids.length > MAX_FILES ||
    ids.some((id) => id.length === 0 || id !== id.trim()) ||
    new Set(ids).size !== ids.length
  ) {
    throw validationError()
  }
  return { accountId, ids }
}

export async function handleImportStatus(request: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user || session.user.id.trim().length === 0) {
    return authenticationRequired()
  }
  try {
    const { accountId, ids } = parseStatusQuery(request)
    const api = createPythonImportApi({
      userId: session.user.id,
      email: session.user.email || undefined,
    })
    const batches: ImportStatusResult["batches"] = []
    for (const id of ids) {
      const batch = await api.getImportBatch(accountId, id)
      if (
        batch.id !== id ||
        batch.account_id !== accountId ||
        !isPythonImportSource(batch.source)
      ) {
        throw contractError()
      }
      batches.push({
        id: batch.id,
        accountId: batch.account_id,
        source: batch.source,
        filename: batch.filename,
        status: batch.status,
        rowsTotal: batch.rows_total ?? 0,
        rowsImported: batch.rows_imported ?? 0,
        rowsSkipped: batch.rows_skipped ?? 0,
      })
    }
    return NextResponse.json({ batches } satisfies ImportStatusResult, {
      headers: NO_STORE_HEADERS,
    })
  } catch (error) {
    return safeAdapterResponse(error)
  }
}
