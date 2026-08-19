import { getServerSession } from "next-auth"
import { NextResponse, type NextRequest } from "next/server"

import { authOptions } from "@/lib/auth"
import { parseCreateManualLiabilityBalanceRequest } from "@/modules/accounts/liability-balance-request-parser"
import { createManualLiabilityBalance } from "@/modules/accounts/server/liability-balance-api"
import {
  normalizeAdapterError,
  toErrorResponse,
  validationError,
} from "@/modules/python-api/server/errors"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }

export async function POST(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const session = await getServerSession(authOptions)
  if (!session?.user || session.user.id.trim().length === 0) {
    return NextResponse.json(
      { error: { code: "authentication_required", message: "Authentication is required." } },
      { status: 401, headers: NO_STORE_HEADERS }
    )
  }

  try {
    const { id } = await context.params
    let payload
    try {
      payload = parseCreateManualLiabilityBalanceRequest(await request.json())
    } catch {
      throw validationError()
    }
    const balance = await createManualLiabilityBalance(
      { userId: session.user.id, email: session.user.email || undefined },
      id,
      payload
    )
    return NextResponse.json(balance, { status: 201, headers: NO_STORE_HEADERS })
  } catch (error) {
    const mapped = toErrorResponse(normalizeAdapterError(error))
    return NextResponse.json(mapped.body, { status: mapped.status, headers: NO_STORE_HEADERS })
  }
}
