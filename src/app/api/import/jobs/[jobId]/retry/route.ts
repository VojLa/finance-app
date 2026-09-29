import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

import { getServerSession } from "next-auth"

import { authOptions } from "@/lib/auth"
import { createPythonImportApi } from "@/modules/imports/python/import-api"
import {
  contractError,
  normalizeAdapterError,
  toErrorResponse,
  validationError,
} from "@/modules/python-api/server/errors"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }

export async function POST(request: NextRequest, context: { params: Promise<{ jobId: string }> }) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) {
    return NextResponse.json(
      { error: { code: "authentication_required", message: "Authentication is required." } },
      { status: 401, headers: NO_STORE_HEADERS }
    )
  }
  try {
    const { jobId } = await context.params
    const body: unknown = await request.json()
    if (
      typeof body !== "object" ||
      body === null ||
      Array.isArray(body) ||
      Object.keys(body).length !== 1 ||
      typeof (body as { accountId?: unknown }).accountId !== "string"
    ) {
      throw validationError()
    }
    const accountId = (body as { accountId: string }).accountId
    if (
      !accountId.trim() ||
      accountId !== accountId.trim() ||
      !jobId.trim() ||
      jobId !== jobId.trim()
    ) {
      throw validationError()
    }
    const job = await createPythonImportApi({
      userId: session.user.id,
      email: session.user.email || undefined,
    }).retryImportJob(accountId, jobId)
    if (job.id !== jobId || job.account_id !== accountId) throw contractError()
    return NextResponse.json(job, { headers: NO_STORE_HEADERS })
  } catch (error) {
    const mapped = toErrorResponse(normalizeAdapterError(error))
    return NextResponse.json(mapped.body, { status: mapped.status, headers: NO_STORE_HEADERS })
  }
}
