import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"
import { importCsv, DuplicateImportError } from "@/modules/imports/import-service"

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const formData = await req.formData()
  const file = formData.get("file") as File | null
  const accountId = formData.get("accountId") as string | null

  if (!file || !accountId) {
    return NextResponse.json({ error: "Chybí soubor nebo accountId" }, { status: 400 })
  }

  const account = await prisma.account.findFirst({ where: { id: accountId, userId: session.user.id } })
  if (!account) return NextResponse.json({ error: "Účet nenalezen" }, { status: 404 })

  try {
    const result = await importCsv({
      content: await file.text(),
      filename: file.name,
      accountId,
      userId: session.user.id,
      source: "trading212",
    })
    return NextResponse.json(result)
  } catch (e) {
    if (e instanceof DuplicateImportError) {
      return NextResponse.json({ error: e.message }, { status: 409 })
    }
    throw e
  }
}
