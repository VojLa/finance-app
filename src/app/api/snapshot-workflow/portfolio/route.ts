import { getServerSession } from "next-auth"
import { NextResponse } from "next/server"

import { authOptions } from "@/lib/auth"
import { normalizeAdapterError, toErrorResponse } from "@/modules/python-api/server/errors"
import { runPortfolioSnapshotWorkflow } from "@/modules/python-api/server/snapshot-workflow"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }

export async function POST() {
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
    const result = await runPortfolioSnapshotWorkflow({
      userId: session.user.id,
      email: session.user.email || undefined,
    })
    return NextResponse.json(result, { headers: NO_STORE_HEADERS })
  } catch (error) {
    const mapped = toErrorResponse(normalizeAdapterError(error))
    return NextResponse.json(mapped.body, {
      status: mapped.status,
      headers: NO_STORE_HEADERS,
    })
  }
}
