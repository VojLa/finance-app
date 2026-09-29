import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"
import { getServerSession } from "next-auth"

import { authOptions } from "@/lib/auth"
import {
  normalizeAdapterError,
  toErrorResponse,
  unavailableError,
  validationError,
} from "@/modules/python-api/server/errors"
import { createAuthenticatedPythonTransport } from "@/modules/python-api/server/transport"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }

function parseAfter(request: NextRequest): string | undefined {
  const values = request.nextUrl.searchParams.getAll("after")
  if (values.length === 0) return undefined
  const after = values[0]
  if (
    values.length !== 1 ||
    [...request.nextUrl.searchParams.keys()].some((key) => key !== "after") ||
    after.length === 0 ||
    after.trim() !== after ||
    after.length > 255
  ) {
    throw validationError()
  }
  return after
}

export async function GET(request: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user || session.user.id.trim().length === 0) {
    return NextResponse.json(
      { error: { code: "authentication_required", message: "Authentication is required." } },
      { status: 401, headers: NO_STORE_HEADERS }
    )
  }

  try {
    const after = parseAfter(request)
    const { client } = createAuthenticatedPythonTransport({
      userId: session.user.id,
      email: session.user.email || undefined,
    })
    const result = await client.GET("/api/v1/read-model-version", {
      params: { query: after === undefined ? {} : { after } },
    })
    if (result.response.status === 204) {
      return new NextResponse(null, { status: 204, headers: NO_STORE_HEADERS })
    }
    if (!result.response.ok || result.data === undefined) throw unavailableError()
    return NextResponse.json(result.data, { headers: NO_STORE_HEADERS })
  } catch (error) {
    const mapped = toErrorResponse(normalizeAdapterError(error))
    return NextResponse.json(mapped.body, { status: mapped.status, headers: NO_STORE_HEADERS })
  }
}
