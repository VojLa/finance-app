import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"
import { parseRaiffeisenbank } from "@/parsers/raiffeisenbank"
import { autoCategorize } from "@/lib/categorize"

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
  const rows = parseRaiffeisenbank(csvText, accountId)

  // Deduplikace podle transactionRef
  const existingRefs = new Set(
    (await prisma.transaction.findMany({
      where: { accountId, transactionRef: { not: null } },
      select: { transactionRef: true },
    })).map(t => t.transactionRef)
  )

  const newRows = rows.filter(r => !r.transactionRef || !existingRefs.has(r.transactionRef))

  if (newRows.length > 0) {
    await prisma.transaction.createMany({
      data: newRows.map(r => ({
        date: r.date,
        amount: r.amount,
        currency: r.currency,
        type: r.type,
        description: r.description || null,
        counterparty: r.counterparty || null,
        transactionRef: r.transactionRef || null,
        accountId: r.accountId,
      })),
    })
    await autoCategorize(accountId)
  }

  await prisma.importLog.create({
    data: {
      filename: file.name,
      source: "raiffeisenbank",
      rowsImported: newRows.length,
      rowsSkipped: rows.length - newRows.length,
      accountId,
    },
  })

  return NextResponse.json({
    imported: newRows.length,
    skipped: rows.length - newRows.length,
  })
}
