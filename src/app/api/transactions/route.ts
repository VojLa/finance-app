import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma, serializePrisma } from "@/lib/prisma"

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

  const accounts = await prisma.account.findMany({
    where: { userId: session.user.id },
    select: { id: true },
  })
  const accountIds = accounts.map(a => a.id)

  const where = {
    accountId: accountId ? accountId : { in: accountIds },
    ...(type ? { type: type as "income" | "expense" | "transfer" } : {}),
    ...(categoryId ? { categoryId } : {}),
    ...(search ? {
      OR: [
        { description: { contains: search, mode: "insensitive" as const } },
        { counterparty: { contains: search, mode: "insensitive" as const } },
      ],
    } : {}),
  }

  const [total, transactions] = await Promise.all([
    prisma.transaction.count({ where }),
    prisma.transaction.findMany({
      where,
      include: { category: true, account: { select: { name: true, currency: true } } },
      orderBy: { date: "desc" },
      skip: (page - 1) * limit,
      take: limit,
    }),
  ])

  return NextResponse.json(serializePrisma({ transactions, total, page, pages: Math.ceil(total / limit) }))
}

export async function PATCH(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { id, categoryId } = await req.json()
  if (!id) return NextResponse.json({ error: "Chybí id" }, { status: 400 })

  const accounts = await prisma.account.findMany({
    where: { userId: session.user.id },
    select: { id: true },
  })
  const accountIds = accounts.map(a => a.id)

  const tx = await prisma.transaction.findFirst({ where: { id, accountId: { in: accountIds } } })
  if (!tx) return NextResponse.json({ error: "Nenalezeno" }, { status: 404 })

  const updated = await prisma.transaction.update({
    where: { id },
    data: { categoryId: categoryId || null },
    include: { category: true },
  })

  return NextResponse.json(serializePrisma(updated))
}
