import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"
import { getLivePrices, clearPriceCache, getCzkRates } from "@/modules/portfolio/rates/service"

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const refresh = req.nextUrl.searchParams.get("refresh") === "true"

  const accounts = await prisma.account.findMany({
    where: { userId: session.user.id },
    include: { holdings: { select: { symbol: true, assetType: true, currency: true } } },
  })

  const symbols = accounts
    .flatMap(a => a.holdings)
    .filter((h, i, arr) => arr.findIndex(x => x.symbol === h.symbol) === i)

  if (refresh) clearPriceCache()

  const [prices, czkRates] = await Promise.all([
    symbols.length > 0 ? getLivePrices(symbols, refresh) : Promise.resolve({}),
    getCzkRates(refresh),
  ])

  return NextResponse.json({
    prices,
    czkRates,
    updatedAt: new Date().toISOString(),
    cached: !refresh,
  })
}
