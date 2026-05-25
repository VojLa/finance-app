import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
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

export async function PATCH(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { id, name, icon, color, type, parentId } = await req.json()
  if (!id) return NextResponse.json({ error: "Chybí id" }, { status: 400 })

  const cat = await prisma.category.findFirst({ where: { id, userId: session.user.id } })
  if (!cat) return NextResponse.json({ error: "Nenalezeno nebo nelze upravit" }, { status: 404 })

  const updated = await prisma.category.update({
    where: { id },
    data: {
      ...(name && { name }),
      ...(icon !== undefined && { icon: icon || null }),
      ...(color !== undefined && { color: color || null }),
      ...(type && { type }),
      ...(parentId !== undefined && { parentId: parentId || null }),
    },
  })

  return NextResponse.json(updated)
}

export async function DELETE(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const id = req.nextUrl.searchParams.get("id")
  if (!id) return NextResponse.json({ error: "Chybí id" }, { status: 400 })

  const cat = await prisma.category.findFirst({ where: { id, userId: session.user.id } })
  if (!cat)
    return NextResponse.json(
      { error: "Nenalezeno nebo nelze smazat (výchozí kategorie)" },
      { status: 404 }
    )

  await prisma.$transaction([
    prisma.category.updateMany({ where: { parentId: id }, data: { parentId: null } }),
    prisma.transaction.updateMany({ where: { categoryId: id }, data: { categoryId: null } }),
    prisma.budgetItem.deleteMany({ where: { categoryId: id } }),
    prisma.category.delete({ where: { id } }),
  ])

  return NextResponse.json({ ok: true })
}
