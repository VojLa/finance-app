import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"

export async function GET(req: NextRequest, { params }: { params: { id: string } }) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const account = await prisma.account.findFirst({
    where: { id: params.id, userId: session.user.id },
  })
  if (!account) return NextResponse.json({ error: "Nenalezeno" }, { status: 404 })

  const shares = await prisma.accountShare.findMany({
    where: { accountId: params.id },
    include: { sharedWith: { select: { id: true, email: true, name: true } } },
    orderBy: { createdAt: "asc" },
  })

  return NextResponse.json(shares)
}

export async function POST(req: NextRequest, { params }: { params: { id: string } }) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const account = await prisma.account.findFirst({
    where: { id: params.id, userId: session.user.id },
  })
  if (!account) return NextResponse.json({ error: "Nenalezeno" }, { status: 404 })

  const { email, role } = await req.json()
  if (!email) return NextResponse.json({ error: "Chybí e-mail" }, { status: 400 })

  if (email === session.user.email) {
    return NextResponse.json({ error: "Nemůžeš sdílet účet sám se sebou" }, { status: 400 })
  }

  const targetUser = await prisma.user.findUnique({ where: { email } })
  if (!targetUser) {
    return NextResponse.json({ error: "Uživatel s tímto e-mailem neexistuje" }, { status: 404 })
  }

  const share = await prisma.accountShare.upsert({
    where: { accountId_sharedWithId: { accountId: params.id, sharedWithId: targetUser.id } },
    update: { role: role === "editor" ? "editor" : "viewer" },
    create: {
      accountId: params.id,
      ownerId: session.user.id,
      sharedWithId: targetUser.id,
      role: role === "editor" ? "editor" : "viewer",
    },
    include: { sharedWith: { select: { id: true, email: true, name: true } } },
  })

  return NextResponse.json(share, { status: 201 })
}
