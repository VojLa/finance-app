import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma, serializePrisma } from "@/lib/prisma"
import { getAccessibleAccountIds, assertAccountAccess } from "@/lib/accountAccess"

const TX_INCLUDE = {
  category: true,
  account: { select: { name: true, currency: true } },
} as const

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { searchParams } = req.nextUrl
  const page = Math.max(1, parseInt(searchParams.get("page") ?? "1"))
  const limit = 50
  const type = searchParams.get("type")
  const categoryId = searchParams.get("categoryId")
  const accountId = searchParams.get("accountId")
  const search = searchParams.get("q")

  const accountIds = await getAccessibleAccountIds(session.user.id, "viewer")

  if (accountId && !accountIds.includes(accountId)) {
    return NextResponse.json(serializePrisma({ transactions: [], total: 0, page: 1, pages: 0 }))
  }

  const where = {
    accountId: accountId ? accountId : { in: accountIds },
    ...(type ? { type: type as "income" | "expense" | "transfer" } : {}),
    ...(categoryId ? { categoryId } : {}),
    ...(search
      ? {
          OR: [
            { description: { contains: search, mode: "insensitive" as const } },
            { counterparty: { contains: search, mode: "insensitive" as const } },
          ],
        }
      : {}),
  }

  const [total, transactions] = await Promise.all([
    prisma.transaction.count({ where }),
    prisma.transaction.findMany({
      where,
      include: TX_INCLUDE,
      orderBy: { date: "desc" },
      skip: (page - 1) * limit,
      take: limit,
    }),
  ])

  return NextResponse.json(
    serializePrisma({ transactions, total, page, pages: Math.ceil(total / limit) })
  )
}

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { date, amount, currency, type, accountId, description, counterparty, note, categoryId } =
    await req.json()

  if (!date || amount == null || !currency || !type || !accountId) {
    return NextResponse.json({ error: "Chybí povinná pole" }, { status: 400 })
  }

  const hasAccess = await assertAccountAccess(accountId, session.user.id, "editor")
  if (!hasAccess) return NextResponse.json({ error: "Účet nenalezen" }, { status: 404 })

  const tx = await prisma.transaction.create({
    data: {
      date: new Date(date),
      amount,
      currency,
      type,
      accountId,
      description: description || null,
      counterparty: counterparty || null,
      note: note || null,
      categoryId: categoryId || null,
    },
    include: TX_INCLUDE,
  })

  return NextResponse.json(serializePrisma(tx), { status: 201 })
}

export async function PATCH(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const body = await req.json()
  const { id } = body
  if (!id) return NextResponse.json({ error: "Chybí id" }, { status: 400 })

  const accountIds = await getAccessibleAccountIds(session.user.id, "editor")

  const tx = await prisma.transaction.findFirst({ where: { id, accountId: { in: accountIds } } })
  if (!tx) return NextResponse.json({ error: "Nenalezeno" }, { status: 404 })

  const data: Record<string, unknown> = {}
  if ("categoryId" in body) data.categoryId = body.categoryId || null
  if ("date" in body) data.date = new Date(body.date)
  if ("amount" in body) data.amount = body.amount
  if ("currency" in body) data.currency = body.currency
  if ("type" in body) data.type = body.type
  if ("description" in body) data.description = body.description || null
  if ("counterparty" in body) data.counterparty = body.counterparty || null
  if ("note" in body) data.note = body.note || null

  const updated = await prisma.transaction.update({
    where: { id },
    data,
    include: TX_INCLUDE,
  })

  return NextResponse.json(serializePrisma(updated))
}

export async function DELETE(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const id = req.nextUrl.searchParams.get("id")
  if (!id) return NextResponse.json({ error: "Chybí id" }, { status: 400 })

  const accountIds = await getAccessibleAccountIds(session.user.id, "editor")

  const tx = await prisma.transaction.findFirst({ where: { id, accountId: { in: accountIds } } })
  if (!tx) return NextResponse.json({ error: "Nenalezeno" }, { status: 404 })

  await prisma.transaction.delete({ where: { id } })
  return NextResponse.json({ ok: true })
}
