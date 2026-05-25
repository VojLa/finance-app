import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"
import { getNetWorthSnapshotHistory } from "@/modules/snapshots"

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const filterAccountId = req.nextUrl.searchParams.get("accountId")

  if (filterAccountId) {
    const account = await prisma.account.findFirst({
      where: { id: filterAccountId, userId: session.user.id },
      select: { id: true },
    })
    if (!account) return NextResponse.json({ error: "Account not found" }, { status: 404 })
  }

  const history = await getNetWorthSnapshotHistory({
    userId: session.user.id,
    accountId: filterAccountId,
  })

  return NextResponse.json(history)
}
