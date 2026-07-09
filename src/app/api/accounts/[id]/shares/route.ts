import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"
import { assertAccountAccess } from "@/lib/accountAccess"

export async function GET(req: NextRequest, { params }: { params: { id: string } }) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const hasAccess = await assertAccountAccess(params.id, session.user.id, "admin")
  if (!hasAccess) return NextResponse.json({ error: "Nenalezeno" }, { status: 404 })

  const members = await prisma.accountMember.findMany({
    where: { accountId: params.id, userId: { not: session.user.id } },
    include: { user: { select: { id: true, email: true, name: true } } },
    orderBy: { createdAt: "asc" },
  })

  return NextResponse.json(
    members.map((member) => ({
      id: member.id,
      role: member.role,
      relationType: member.relationType,
      sharedWith: member.user,
    }))
  )
}

export async function POST(req: NextRequest, { params }: { params: { id: string } }) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const hasAccess = await assertAccountAccess(params.id, session.user.id, "admin")
  if (!hasAccess) return NextResponse.json({ error: "Nenalezeno" }, { status: 404 })

  const { email, role } = await req.json()
  if (!email) return NextResponse.json({ error: "Chybi e-mail" }, { status: 400 })

  if (email === session.user.email) {
    return NextResponse.json({ error: "Nemuzes sdilet ucet sam se sebou" }, { status: 400 })
  }

  const targetUser = await prisma.user.findUnique({ where: { email } })
  if (!targetUser) {
    return NextResponse.json({ error: "Uzivatel s timto e-mailem neexistuje" }, { status: 404 })
  }

  const memberRole = role === "editor" ? "editor" : "viewer"
  const member = await prisma.accountMember.upsert({
    where: { accountId_userId: { accountId: params.id, userId: targetUser.id } },
    update: { role: memberRole },
    create: {
      accountId: params.id,
      userId: targetUser.id,
      role: memberRole,
      relationType: "collaborator",
      invitedById: session.user.id,
      acceptedAt: new Date(),
    },
    include: { user: { select: { id: true, email: true, name: true } } },
  })

  return NextResponse.json(
    {
      id: member.id,
      role: member.role,
      relationType: member.relationType,
      sharedWith: member.user,
    },
    { status: 201 }
  )
}
