import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

import { DuplicateImportError, importCsvFilesAsync } from "@/modules/imports"
import { getImportContext, handleImportError } from "@/imports/utils/api"

export async function POST(req: NextRequest) {
  try {
    const context = await getImportContext(req)
    if (!context.ok) return context.response

    const files = await Promise.all(
      context.files.map(async (file) => ({
        content: await file.text(),
        filename: file.name,
      }))
    )
    const result = await importCsvFilesAsync({
      files,
      accountId: context.accountId,
      userId: context.userId,
      source: "raiffeisenbank",
    })

    return NextResponse.json({
      accepted: result.accepted,
      batchIds: result.batchIds,
      files: result.files,
    })
  } catch (error) {
    if (error instanceof DuplicateImportError) {
      return NextResponse.json({ error: error.message }, { status: 409 })
    }
    return handleImportError(error, "Raiffeisenbank import error")
  }
}
