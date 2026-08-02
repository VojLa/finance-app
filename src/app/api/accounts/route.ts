import { getServerSession } from "next-auth"
import { NextResponse, type NextRequest } from "next/server"

import { authOptions } from "@/lib/auth"
import type { CreateAccountRequest } from "@/modules/accounts/account-contract"
import { createAccount, listAccounts } from "@/modules/accounts/server/account-api"
import {
  normalizeAdapterError,
  toErrorResponse,
  validationError,
} from "@/modules/python-api/server/errors"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }

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

export async function GET() {
  const session = await getServerSession(authOptions)
  if (!session?.user || session.user.id.trim().length === 0) {
    return authenticationRequired()
  }

  try {
    const accounts = await listAccounts({
      userId: session.user.id,
      email: session.user.email || undefined,
    })
    return NextResponse.json(accounts, { headers: NO_STORE_HEADERS })
  } catch (error) {
    const mapped = toErrorResponse(normalizeAdapterError(error))
    return NextResponse.json(mapped.body, {
      status: mapped.status,
      headers: NO_STORE_HEADERS,
    })
  }
}

export async function POST(request: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user || session.user.id.trim().length === 0) {
    return authenticationRequired()
  }

  try {
    let payload: CreateAccountRequest
    try {
      payload = (await request.json()) as CreateAccountRequest
    } catch {
      throw validationError()
    }
    const account = await createAccount(
      {
        userId: session.user.id,
        email: session.user.email || undefined,
      },
      payload
    )
    return NextResponse.json(account, { status: 201, headers: NO_STORE_HEADERS })
  } catch (error) {
    const mapped = toErrorResponse(normalizeAdapterError(error))
    return NextResponse.json(mapped.body, {
      status: mapped.status,
      headers: NO_STORE_HEADERS,
    })
  }
}
