import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"

export async function GET() {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const [ownAccounts, sharedEntries] = await Promise.all([
    prisma.account.findMany({
      where: { userId: session.user.id },
      orderBy: { createdAt: "asc" },
    }),
    prisma.accountShare.findMany({
      where: { sharedWithId: session.user.id },
      include: { account: true },
    }),
  ])

  const sharedAccounts = sharedEntries.map((s) => ({
    ...s.account,
    isShared: true,
    shareRole: s.role,
    ownerEmail: undefined,
  }))

  return NextResponse.json([...ownAccounts, ...sharedAccounts])
}

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { name, type, currency, color } = await req.json()

  if (!name || !type || !currency) {
    return NextResponse.json({ error: "Chybí povinná pole" }, { status: 400 })
  }

  const VALID_TYPES = [
    "bank",
    "cash",
    "savings",
    "broker",
    "exchange",
    "crypto_wallet",
    "credit_card",
    "loan",
    "mortgage",
  ]
  if (!VALID_TYPES.includes(type)) {
    return NextResponse.json({ error: "Neplatný typ účtu" }, { status: 400 })
  }

  try {
    const account = await prisma.account.create({
      data: { name, type, currency, color: color || null, userId: session.user.id },
    })
    return NextResponse.json(account, { status: 201 })
  } catch (err) {
    console.error("Account create error:", err)
    return NextResponse.json({ error: "Nepodařilo se vytvořit účet" }, { status: 500 })
  }
}

export async function PATCH(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { searchParams } = new URL(req.url)
  const id = searchParams.get("id")
  if (!id) return NextResponse.json({ error: "Chybí id" }, { status: 400 })

  const account = await prisma.account.findFirst({ where: { id, userId: session.user.id } })
  if (!account) return NextResponse.json({ error: "Nenalezeno" }, { status: 404 })

  const { name, type, currency, color } = await req.json()

  const updated = await prisma.account.update({
    where: { id },
    data: {
      ...(name && { name }),
      ...(type && { type }),
      ...(currency && { currency }),
      color: color ?? account.color,
    },
  })

  return NextResponse.json(updated)
}

export async function DELETE(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { searchParams } = new URL(req.url)
  const id = searchParams.get("id")
  if (!id) return NextResponse.json({ error: "Chybí id" }, { status: 400 })

  const account = await prisma.account.findFirst({ where: { id, userId: session.user.id } })
  if (!account) return NextResponse.json({ error: "Nenalezeno" }, { status: 404 })

  const transactions = await prisma.transaction.findMany({
    where: { accountId: id },
    select: { id: true },
  })
  const transactionIds = transactions.map((tx) => tx.id)

  await prisma.$transaction([
    prisma.transactionPair.deleteMany({
      where: {
        OR: [
          { fromTransactionId: { in: transactionIds } },
          { toTransactionId: { in: transactionIds } },
        ],
      },
    }),
    prisma.portfolioSnapshotItem.deleteMany({ where: { accountId: id } }),
    prisma.transaction.deleteMany({ where: { accountId: id } }),
    prisma.investmentTransaction.deleteMany({ where: { accountId: id } }),
    prisma.holding.deleteMany({ where: { accountId: id } }),
    prisma.importBatch.deleteMany({ where: { accountId: id } }),
    prisma.account.delete({ where: { id } }),
  ])

  return NextResponse.json({ ok: true })
}
