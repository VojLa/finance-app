import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"

export async function GET() {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const categories = await prisma.category.findMany({
    where: { OR: [{ isDefault: true }, { userId: session.user.id }] },
    include: { children: true },
    orderBy: { name: "asc" },
  })

  return NextResponse.json(categories)
}

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { name, icon, color, type, parentId } = await req.json()
  if (!name || !type) return NextResponse.json({ error: "Chybí name nebo type" }, { status: 400 })

  const category = await prisma.category.create({
    data: { name, icon, color, type, parentId: parentId || null, userId: session.user.id },
  })

  return NextResponse.json(category, { status: 201 })
}
