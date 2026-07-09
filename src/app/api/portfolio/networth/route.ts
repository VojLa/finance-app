import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { assertAccountAccess } from "@/lib/accountAccess"
import { getNetWorthSnapshotHistory } from "@/modules/snapshots"

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const filterAccountId = req.nextUrl.searchParams.get("accountId")

  if (filterAccountId) {
    const hasAccess = await assertAccountAccess(filterAccountId, session.user.id, "viewer")
    if (!hasAccess) return NextResponse.json({ error: "Account not found" }, { status: 404 })
  }

  const history = await getNetWorthSnapshotHistory({
    userId: session.user.id,
    accountId: filterAccountId,
  })

  return NextResponse.json(history)
}
