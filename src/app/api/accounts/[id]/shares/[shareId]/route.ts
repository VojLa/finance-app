import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"
import { assertAccountAccess } from "@/lib/accountAccess"

export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string; shareId: string } }
) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const hasAccess = await assertAccountAccess(params.id, session.user.id, "admin")
  if (!hasAccess) return NextResponse.json({ error: "Nenalezeno" }, { status: 404 })

  const member = await prisma.accountMember.findFirst({
    where: { id: params.shareId, accountId: params.id },
  })
  if (!member) return NextResponse.json({ error: "Nenalezeno" }, { status: 404 })

  if (member.role === "owner") {
    const ownerCount = await prisma.accountMember.count({
      where: { accountId: params.id, role: "owner" },
    })
    if (ownerCount <= 1) {
      return NextResponse.json(
        { error: "Ucet musi mit alespon jednoho vlastnika" },
        { status: 400 }
      )
    }
  }

  await prisma.accountMember.delete({ where: { id: params.shareId } })

  return NextResponse.json({ ok: true })
}
