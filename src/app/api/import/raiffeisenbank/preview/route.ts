import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"

import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"
import { assertAccountAccess } from "@/lib/accountAccess"
import { parseRaiffeisenbank } from "@/imports/raiffeisenbank/parser"

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const formData = await req.formData()
  const file = formData.get("file")
  const accountId = formData.get("accountId")

  if (!(file instanceof File)) return NextResponse.json({ error: "Missing file" }, { status: 400 })
  if (typeof accountId !== "string" || !accountId)
    return NextResponse.json({ error: "Missing accountId" }, { status: 400 })

  const hasAccess = await assertAccountAccess(accountId, session.user.id, "editor")
  if (!hasAccess) return NextResponse.json({ error: "Account not found" }, { status: 404 })

  const csvText = await file.text()
  const rows = parseRaiffeisenbank(csvText, accountId)

  if (rows.length === 0) {
    return NextResponse.json({ rows: [], counts: { new: 0, duplicate: 0 } })
  }

  const externalIds = rows.map((r) => r.externalId).filter(Boolean)
  const existingIds =
    externalIds.length > 0
      ? new Set(
          (
            await prisma.transaction.findMany({
              where: { accountId, externalId: { in: externalIds } },
              select: { externalId: true },
            })
          )
            .map((t) => t.externalId)
            .filter((id): id is string => id !== null)
        )
      : new Set<string>()

  const previewRows = rows.map((r) => ({
    date: r.date.toISOString(),
    amount: r.amount,
    currency: r.currency,
    type: r.type,
    description: r.description,
    counterparty: r.counterparty,
    isDuplicate: existingIds.has(r.externalId),
  }))

  return NextResponse.json({
    rows: previewRows,
    counts: {
      new: previewRows.filter((r) => !r.isDuplicate).length,
      duplicate: previewRows.filter((r) => r.isDuplicate).length,
    },
  })
}
