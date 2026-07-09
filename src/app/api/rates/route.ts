import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"
import { getAccessibleAccountIds } from "@/lib/accountAccess"
import { getLivePrices, clearPriceCache, getCzkRates } from "@/modules/portfolio/rates/service"
import { createPortfolioSnapshot } from "@/modules/snapshots"

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const refresh = req.nextUrl.searchParams.get("refresh") === "true"

  const accountIds = await getAccessibleAccountIds(session.user.id, "viewer")
  const accounts = await prisma.account.findMany({
    where: { id: { in: accountIds } },
    include: { holdings: { select: { symbol: true, assetType: true, currency: true } } },
  })

  const symbols = accounts
    .flatMap((a) => a.holdings)
    .filter((h, i, arr) => arr.findIndex((x) => x.symbol === h.symbol) === i)

  if (refresh) clearPriceCache()

  const [prices, czkRates] = await Promise.all([
    symbols.length > 0 ? getLivePrices(symbols, refresh) : Promise.resolve({}),
    getCzkRates(refresh),
  ])

  if (refresh) {
    await createPortfolioSnapshot({
      userId: session.user.id,
      source: "price_refresh",
      granularity: "minute",
    })
  }

  return NextResponse.json({
    prices,
    czkRates,
    updatedAt: new Date().toISOString(),
    cached: !refresh,
  })
}
