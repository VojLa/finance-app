import { NextResponse, type NextRequest } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { getAccessibleAccountIds } from "@/lib/accountAccess"
import { prisma } from "@/lib/prisma"
import { recalculateHoldings } from "@/modules/portfolio/positions/calculations"
import { createDailyAccountSnapshotsFromImport, createNetWorthSnapshot } from "@/modules/snapshots"

const INVESTMENT_ACCOUNT_TYPES = new Set(["broker", "exchange", "crypto_wallet"])

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const body = await req.json().catch(() => ({}))
  const requestedAccountId = typeof body.accountId === "string" ? body.accountId : null

  const accessibleIds = await getAccessibleAccountIds(session.user.id, "editor")
  const accounts = await prisma.account.findMany({
    where: {
      id: requestedAccountId ? requestedAccountId : { in: accessibleIds },
      type: { in: Array.from(INVESTMENT_ACCOUNT_TYPES) as never },
    },
    select: { id: true, name: true },
  })

  const allowedAccounts = accounts.filter((account) => accessibleIds.includes(account.id))
  if (requestedAccountId && allowedAccounts.length === 0) {
    return NextResponse.json({ error: "Ucet nenalezen nebo k nemu nemas pristup" }, { status: 404 })
  }

  let snapshots = 0
  let validations = 0
  const recalculatedAccounts: Array<{ id: string; name: string; snapshots: number }> = []

  for (const account of allowedAccounts) {
    await recalculateHoldings(account.id)
    const result = await createDailyAccountSnapshotsFromImport({ accountId: account.id })
    snapshots += result.snapshots
    validations += result.validations
    recalculatedAccounts.push({ id: account.id, name: account.name, snapshots: result.snapshots })
  }

  await createNetWorthSnapshot({ userId: session.user.id })

  return NextResponse.json({
    ok: true,
    accounts: recalculatedAccounts,
    snapshots,
    validations,
  })
}
