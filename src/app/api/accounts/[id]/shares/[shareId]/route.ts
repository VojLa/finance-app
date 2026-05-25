import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"

export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string; shareId: string } }
) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const share = await prisma.accountShare.findFirst({
    where: { id: params.shareId, accountId: params.id, ownerId: session.user.id },
  })
  if (!share) return NextResponse.json({ error: "Nenalezeno" }, { status: 404 })

  await prisma.accountShare.delete({ where: { id: params.shareId } })

  return NextResponse.json({ ok: true })
}
