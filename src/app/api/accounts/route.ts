import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"

export async function GET() {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const accounts = await prisma.account.findMany({
    where: { userId: session.user.id },
    orderBy: { createdAt: "asc" },
  })

  return NextResponse.json(accounts)
}

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { name, type, currency, color } = await req.json()

  if (!name || !type || !currency) {
    return NextResponse.json({ error: "Chybí povinná pole" }, { status: 400 })
  }

  const account = await prisma.account.create({
    data: { name, type, currency, color: color || null, userId: session.user.id },
  })

  return NextResponse.json(account, { status: 201 })
}

export async function DELETE(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { searchParams } = new URL(req.url)
  const id = searchParams.get("id")
  if (!id) return NextResponse.json({ error: "Chybí id" }, { status: 400 })

  const account = await prisma.account.findFirst({ where: { id, userId: session.user.id } })
  if (!account) return NextResponse.json({ error: "Nenalezeno" }, { status: 404 })

  await prisma.account.delete({ where: { id } })
  return NextResponse.json({ ok: true })
}
