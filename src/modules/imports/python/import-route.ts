import "server-only"

import { createHash } from "node:crypto"

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
import { createPythonImportApi } from "./import-api"
import { isPythonImportSource, type PythonImportSource } from "./import-contract"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }
const MAX_FILES = 10
const MAX_FILE_SIZE = 64 * 1024 * 1024
const MAX_TOTAL_SIZE = 64 * 1024 * 1024

function authenticationRequired() {
  return NextResponse.json(
    { error: { code: "authentication_required", message: "Authentication is required." } },
    { status: 401, headers: NO_STORE_HEADERS }
  )
}

function errorResponse(error: unknown) {
  const mapped = toErrorResponse(normalizeAdapterError(error))
  return NextResponse.json(mapped.body, { status: mapped.status, headers: NO_STORE_HEADERS })
}

function formAccountId(formData: FormData): string {
  const values = formData.getAll("accountId")
  if (
    values.length !== 1 ||
    typeof values[0] !== "string" ||
    !values[0].trim() ||
    values[0] !== values[0].trim()
  ) {
    throw validationError()
  }
  return values[0]
}

function formSource(formData: FormData): PythonImportSource {
  const values = formData.getAll("source")
  if (values.length !== 1 || !isPythonImportSource(values[0])) throw validationError()
  return values[0]
}

function formFiles(formData: FormData): File[] {
  if (![...formData.keys()].every((key) => ["accountId", "source", "file"].includes(key))) {
    throw validationError()
  }
  const values = formData.getAll("file")
  const files = values.filter((value): value is File => value instanceof File)
  if (files.length === 0 || files.length !== values.length || files.length > MAX_FILES) {
    throw validationError()
  }
  if (
    files.some(
      (file) =>
        !file.name ||
        !file.name.toLowerCase().endsWith(".csv") ||
        file.size === 0 ||
        file.size > MAX_FILE_SIZE
    ) ||
    files.reduce((total, file) => total + file.size, 0) > MAX_TOTAL_SIZE
  ) {
    throw validationError()
  }
  return files
}

/** Register and upload files, then hand the entire durable workflow to Python. */
export async function handleImportPost(request: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id || session.user.id !== session.user.id.trim())
    return authenticationRequired()
  try {
    const formData = await request.formData().catch(() => {
      throw validationError()
    })
    const accountId = formAccountId(formData)
    const source = formSource(formData)
    const files = formFiles(formData)
    const api = createPythonImportApi({
      userId: session.user.id,
      email: session.user.email || undefined,
    })
    const batchIds: string[] = []
    const rejectedFiles: Array<{ filename: string; code: string; message: string }> = []
    let firstFailure: unknown
    for (const file of files) {
      try {
        const bytes = new Uint8Array(await file.arrayBuffer())
        const checksum = createHash("sha256").update(bytes).digest("hex")
        const batch = await api.createImportBatch(accountId, {
          source,
          filename: file.name,
          file_size: bytes.byteLength,
          file_encoding: null,
          checksum,
        })
        if (
          batch.account_id !== accountId ||
          batch.source !== source ||
          batch.filename !== file.name ||
          batch.file_size !== bytes.byteLength ||
          batch.file_encoding !== null ||
          batch.checksum !== checksum
        ) {
          throw contractError()
        }
        if (batch.status === "pending") {
          const upload = await api.uploadImportFile(accountId, batch.id, bytes)
          if (
            upload.batch_id !== batch.id ||
            upload.size !== bytes.byteLength ||
            upload.checksum !== checksum
          ) {
            throw contractError()
          }
        }
        if (!batchIds.includes(batch.id)) batchIds.push(batch.id)
      } catch (error) {
        firstFailure ??= error
        const mapped = toErrorResponse(normalizeAdapterError(error))
        rejectedFiles.push({
          filename: file.name,
          code: mapped.body.error.code,
          message: mapped.body.error.message,
        })
      }
    }
    if (batchIds.length === 0) throw firstFailure ?? contractError()
    const job = await api.startImportJob(accountId, [...batchIds].sort())
    if (job.account_id !== accountId) throw contractError()
    return NextResponse.json(
      { job, acceptedBatchIds: [...batchIds].sort(), rejectedFiles },
      { status: 202, headers: NO_STORE_HEADERS }
    )
  } catch (error) {
    return errorResponse(error)
  }
}
