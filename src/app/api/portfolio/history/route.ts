import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { assertAccountAccess } from "@/lib/accountAccess"
import { getPortfolioSnapshotHistory, type PortfolioHistoryRange } from "@/modules/snapshots"

const RANGES = new Set(["1W", "1M", "3M", "6M", "1Y", "ALL"])

function parseRange(value: string | null): PortfolioHistoryRange {
  return RANGES.has(value ?? "") ? (value as PortfolioHistoryRange) : "1Y"
}

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const filterAccountId = req.nextUrl.searchParams.get("accountId")
  const range = parseRange(req.nextUrl.searchParams.get("range"))

  if (filterAccountId) {
    const hasAccess = await assertAccountAccess(filterAccountId, session.user.id, "viewer")
    if (!hasAccess) return NextResponse.json({ error: "Account not found" }, { status: 404 })
  }

  const history = await getPortfolioSnapshotHistory({
    userId: session.user.id,
    accountId: filterAccountId,
    range,
  })

  return NextResponse.json(history)
}
