import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

import { DuplicateImportError, importCsv } from "@/modules/imports"
import { getImportContext, handleImportError } from "@/imports/utils/api"

export async function POST(req: NextRequest) {
  try {
    const context = await getImportContext(req)
    if (!context.ok) return context.response

    const csvText = await context.file.text()
    const result = await importCsv({
      content: csvText,
      filename: context.file.name,
      accountId: context.accountId,
      userId: context.userId,
      source: "raiffeisenbank",
    })

    return NextResponse.json({
      imported: result.imported,
      skipped: result.skipped,
      duplicates: result.duplicates,
      parsed: result.parsed,
      rowsTotal: result.rowsTotal,
      duplicateFile: result.duplicateFile,
    })
  } catch (error) {
    if (error instanceof DuplicateImportError) {
      return NextResponse.json({ error: error.message }, { status: 409 })
    }
    return handleImportError(error, "Raiffeisenbank import error")
  }
}
