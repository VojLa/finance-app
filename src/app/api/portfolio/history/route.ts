import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"

import { authOptions } from "@/lib/auth"
import {
  SNAPSHOT_PORTFOLIO_HISTORY_RANGES,
  type SnapshotPortfolioHistoryRange,
} from "@/modules/portfolio/snapshot-history-contract"
import {
  normalizeAdapterError,
  toErrorResponse,
  validationError,
} from "@/modules/python-api/server/errors"
import { readGenerationPortfolioHistory } from "@/modules/python-api/server/portfolio-history"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }
const RANGES = new Set<SnapshotPortfolioHistoryRange>(SNAPSHOT_PORTFOLIO_HISTORY_RANGES)

type HistoryRequest = Readonly<{
  range: SnapshotPortfolioHistoryRange
  accountId?: string
}>

function parseRequest(request: NextRequest): HistoryRequest {
  const parameters = request.nextUrl.searchParams
  if ([...parameters].length === 0) return { range: "1Y" }

  const ranges = parameters.getAll("range")
  const accountIds = parameters.getAll("accountId")
  if (
    ranges.length !== 1 ||
    accountIds.length > 1 ||
    [...parameters.keys()].some((key) => key !== "range" && key !== "accountId")
  ) {
    throw validationError()
  }
  const value = ranges[0]
  if (!RANGES.has(value as SnapshotPortfolioHistoryRange)) {
    throw validationError()
  }
  const accountId = accountIds[0]
  if (accountId !== undefined && (accountId.length === 0 || accountId.trim() !== accountId)) {
    throw validationError()
  }
  return { range: value as SnapshotPortfolioHistoryRange, accountId }
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
    const historyRequest = parseRequest(request)
    const history = await readGenerationPortfolioHistory(
      {
        userId: session.user.id,
        email: session.user.email || undefined,
      },
      historyRequest.range,
      undefined,
      historyRequest.accountId
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
