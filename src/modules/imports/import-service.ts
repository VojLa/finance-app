import crypto from "crypto"
import { prisma } from "@/lib/prisma"
import type { ImportSource } from "@prisma/client"
import { runImport } from "./run-import"
import { getImportDefinition } from "./import-registry"

export type { ImportResult } from "./run-import"

export class DuplicateImportError extends Error {
  constructor(message = "Tento soubor byl jiz importovan") {
    super(message)
    this.name = "DuplicateImportError"
  }
}

function firstParsedDate(rows: Array<{ date?: Date | null }>) {
  return rows.reduce<Date | null>((first, row) => {
    if (!row.date) return first
    return !first || row.date < first ? row.date : first
  }, null)
}

export async function importCsv({
  content,
  filename,
  accountId,
  userId,
  source,
}: {
  content: string
  filename: string
  accountId: string
  userId: string
  source: ImportSource
}) {
  const checksum = crypto.createHash("sha256").update(content).digest("hex")
  const definition = getImportDefinition(source)
  const parseResult = definition.parse(content, accountId)
  const rowsTotal = parseResult.rowsTotal
  const importStartDate = firstParsedDate(parseResult.rows)

  const existing = await prisma.importBatch.findFirst({ where: { userId, accountId, checksum } })
  if (existing) {
    const storedProcessed = (existing.rowsImported ?? 0) + (existing.rowsSkipped ?? 0)
    const parsed = storedProcessed > 0 ? storedProcessed : parseResult.rows.length

    if (existing.status === "failed") {
      await prisma.importBatch.update({
        where: { id: existing.id },
        data: { status: "processing", completedAt: null },
      })

      try {
        await definition.afterCompleted?.({
          userId,
          accountId,
          importBatchId: existing.id,
          importStartDate,
        })

        await prisma.importBatch.update({
          where: { id: existing.id },
          data: {
            rowsTotal,
            rowsImported: existing.rowsImported ?? 0,
            rowsSkipped: existing.rowsSkipped ?? 0,
            status: "completed",
            completedAt: new Date(),
          },
        })
      } catch (error) {
        await prisma.importBatch.update({
          where: { id: existing.id },
          data: {
            status: "failed",
            completedAt: new Date(),
          },
        })
        throw error
      }

      return {
        imported: 0,
        skipped: parsed,
        duplicates: parsed,
        parsed,
        rowsTotal,
        duplicateFile: true,
        parseIssues: parseResult.issues,
        warnings: [],
      }
    }

    return {
      imported: 0,
      skipped: parsed,
      duplicates: parsed,
      parsed,
      rowsTotal,
      duplicateFile: true,
      parseIssues: parseResult.issues,
      warnings: [],
    }
  }

  const batch = await prisma.importBatch.create({
    data: {
      checksum,
      filename,
      source,
      accountId,
      userId,
      status: "processing",
    },
  })

  try {
    const postProcess = definition.postProcess
    const result = await runImport({
      parseResult,
      accountId,
      importBatchId: batch.id,
      fetchExistingIds: definition.fetchExistingIds,
      saveRows: definition.saveRows,
      postProcess: postProcess ? () => postProcess(accountId) : undefined,
    })

    await prisma.importBatch.update({
      where: { id: batch.id },
      data: {
        rowsTotal: result.rowsTotal,
        rowsImported: result.imported,
        rowsSkipped: result.skipped,
        status: "completed",
        completedAt: new Date(),
      },
    })

    await definition.afterCompleted?.({ userId, accountId, importBatchId: batch.id, importStartDate })

    return result
  } catch (error) {
    await prisma.importBatch.update({
      where: { id: batch.id },
      data: {
        status: "failed",
        completedAt: new Date(),
      },
    })
    throw error
  }
}
