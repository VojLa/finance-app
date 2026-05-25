import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"

import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"
import { assertAccountAccess } from "@/lib/accountAccess"
import type { ImportSource } from "@prisma/client"

type ImportContext =
  | {
      ok: true
      file: File
      accountId: string
      userId: string
    }
  | {
      ok: false
      response: NextResponse
    }

export async function getImportContext(req: NextRequest): Promise<ImportContext> {
  const session = await getServerSession(authOptions)
  if (!session) {
    return {
      ok: false,
      response: NextResponse.json({ error: "Unauthorized" }, { status: 401 }),
    }
  }

  const formData = await req.formData()
  const file = formData.get("file")
  const accountId = formData.get("accountId")

  if (!(file instanceof File)) {
    return {
      ok: false,
      response: NextResponse.json({ error: "Missing import file" }, { status: 400 }),
    }
  }

  if (typeof accountId !== "string" || !accountId) {
    return {
      ok: false,
      response: NextResponse.json({ error: "Missing accountId" }, { status: 400 }),
    }
  }

  const hasAccess = await assertAccountAccess(accountId, session.user.id, "editor")
  if (!hasAccess) {
    return {
      ok: false,
      response: NextResponse.json({ error: "Přístup odepřen" }, { status: 403 }),
    }
  }

  return {
    ok: true,
    file,
    accountId,
    userId: session.user.id,
  }
}

export function handleImportError(error: unknown, message: string): NextResponse {
  console.error(message, error)
  return NextResponse.json({ error: message }, { status: 500 })
}

export async function writeImportLog({
  filename,
  source,
  rowsImported,
  rowsSkipped,
  accountId,
}: {
  filename: string
  source: ImportSource
  rowsImported: number
  rowsSkipped: number
  accountId: string
}): Promise<void> {
  await prisma.importBatch.updateMany({
    where: { accountId, filename, source },
    data: {
      rowsTotal: rowsImported + rowsSkipped,
      rowsImported,
      rowsSkipped,
      status: "completed",
      completedAt: new Date(),
    },
  })
}
