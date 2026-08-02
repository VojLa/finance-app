import { getServerSession } from "next-auth"
import { NextResponse, type NextRequest } from "next/server"

import { authOptions } from "@/lib/auth"
import { parseUpdateAccountRequest } from "@/modules/accounts/account-request-parser"
import { updateAccount } from "@/modules/accounts/server/account-api"
import {
  normalizeAdapterError,
  toErrorResponse,
  validationError,
} from "@/modules/python-api/server/errors"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }

export async function PATCH(request: NextRequest, { params }: { params: { id: string } }) {
  const session = await getServerSession(authOptions)
  if (!session?.user || session.user.id.trim().length === 0) {
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

  try {
    let payload
    try {
      payload = parseUpdateAccountRequest(await request.json())
    } catch {
      throw validationError()
    }
    const account = await updateAccount(
      {
        userId: session.user.id,
        email: session.user.email || undefined,
      },
      params.id,
      payload
    )
    return NextResponse.json(account, { headers: NO_STORE_HEADERS })
  } catch (error) {
    const mapped = toErrorResponse(normalizeAdapterError(error))
    return NextResponse.json(mapped.body, {
      status: mapped.status,
      headers: NO_STORE_HEADERS,
    })
  }
}
