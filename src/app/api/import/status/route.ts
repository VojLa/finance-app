import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"

function parseIssue(row: {
  rowNumber: number
  rawData: unknown
  validationErrors: unknown
  errorMessage: string | null
}) {
  const validation =
    row.validationErrors && typeof row.validationErrors === "object"
      ? (row.validationErrors as Record<string, unknown>)
      : {}

  const storedRowNumber = row.rowNumber > 0 ? Math.floor(row.rowNumber / 1000) : undefined

  return {
    severity: validation.severity ?? "warning",
    code: validation.code ?? "import_issue",
    message: validation.message ?? row.errorMessage ?? "Import row needs review.",
    rowNumber: storedRowNumber,
    raw: row.rawData,
  }
}

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const ids = req.nextUrl.searchParams
    .get("ids")
    ?.split(",")
    .map((id) => id.trim())
    .filter(Boolean)

  if (!ids || ids.length === 0) {
    return NextResponse.json({ error: "Missing ids" }, { status: 400 })
  }

  const batches = await prisma.importBatch.findMany({
    where: { id: { in: ids }, userId: session.user.id },
    include: {
      importRows: {
        where: { status: { in: ["needs_review", "failed"] } },
        orderBy: { createdAt: "asc" },
      },
      importLogs: {
        where: { level: "error" },
        orderBy: { createdAt: "desc" },
        take: 1,
      },
    },
    orderBy: { createdAt: "asc" },
  })

  return NextResponse.json({
    batches: batches.map((batch) => ({
      id: batch.id,
      filename: batch.filename,
      status: batch.status,
      imported: batch.rowsImported ?? 0,
      skipped: batch.rowsSkipped ?? 0,
      duplicates: batch.rowsSkipped ?? 0,
      parsed: (batch.rowsImported ?? 0) + (batch.rowsSkipped ?? 0),
      rowsTotal: batch.rowsTotal ?? 0,
      completedAt: batch.completedAt,
      error: batch.importLogs[0]?.message ?? null,
      parseIssues: batch.importRows.map(parseIssue),
    })),
  })
}
