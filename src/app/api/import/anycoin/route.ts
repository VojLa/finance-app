import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"
import { parseAnycoin } from "@/parsers/anycoin"
import { recalculateHoldings } from "@/lib/portfolio"

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const formData = await req.formData()
  const file = formData.get("file") as File | null
  const accountId = formData.get("accountId") as string | null

  if (!file || !accountId) {
    return NextResponse.json({ error: "Chybí soubor nebo accountId" }, { status: 400 })
  }

  const account = await prisma.account.findFirst({ where: { id: accountId, userId: session.user.id } })
  if (!account) return NextResponse.json({ error: "Účet nenalezen" }, { status: 404 })

  const csvText = await file.text()
  const transactions = parseAnycoin(csvText, accountId)

  const existingIds = new Set(
    (await prisma.investmentTransaction.findMany({
      where: { accountId, externalId: { not: null } },
      select: { externalId: true },
    })).map(t => t.externalId)
  )

  const newTransactions = transactions.filter(
    t => !t.externalId || !existingIds.has(t.externalId)
  )

  if (newTransactions.length > 0) {
    await prisma.investmentTransaction.createMany({ data: newTransactions })
    await recalculateHoldings(accountId)
  }

  await prisma.importLog.create({
    data: {
      filename: file.name,
      source: "anycoin",
      rowsImported: newTransactions.length,
      rowsSkipped: transactions.length - newTransactions.length,
      accountId,
    },
  })

  return NextResponse.json({
    imported: newTransactions.length,
    skipped: transactions.length - newTransactions.length,
  })
}
