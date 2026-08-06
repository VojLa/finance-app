import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"

import { authOptions } from "@/lib/auth"
import type { SnapshotPortfolioHistoryRange } from "@/modules/portfolio/snapshot-history-contract"
import {
  normalizeAdapterError,
  toErrorResponse,
  validationError,
} from "@/modules/python-api/server/errors"
import { readSnapshotBackedPortfolioHistory } from "@/modules/python-api/server/portfolio-history"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }
const RANGES = new Set<SnapshotPortfolioHistoryRange>(["1W", "1M", "3M", "6M", "1Y", "ALL"])

function parseRange(request: NextRequest): SnapshotPortfolioHistoryRange {
  const entries = [...request.nextUrl.searchParams.entries()]
  if (entries.length === 0) return "1Y"
  if (entries.length !== 1 || entries[0]?.[0] !== "range") {
    throw validationError()
  }
  const value = entries[0][1]
  if (!RANGES.has(value as SnapshotPortfolioHistoryRange)) {
    throw validationError()
  }
  return value as SnapshotPortfolioHistoryRange
}

export async function GET(request: NextRequest) {
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
    const history = await readSnapshotBackedPortfolioHistory(
      {
        userId: session.user.id,
        email: session.user.email || undefined,
      },
      parseRange(request)
    )
    return NextResponse.json(history, { headers: NO_STORE_HEADERS })
  } catch (error) {
    const mapped = toErrorResponse(normalizeAdapterError(error))
    return NextResponse.json(mapped.body, {
      status: mapped.status,
      headers: NO_STORE_HEADERS,
    })
  }
}
