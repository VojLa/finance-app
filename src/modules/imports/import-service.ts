import crypto from "crypto"
import { prisma } from "@/lib/prisma"
import type { ImportSource } from "@prisma/client"
import { runImport } from "./run-import"
import { getImportDefinition } from "./import-registry"
import type { ParseIssue } from "./parsers/shared/result"

export type { ImportResult } from "./run-import"

const runningImports = new Set<string>()

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

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function processedRows(batch: { rowsImported: number | null; rowsSkipped: number | null }) {
  return (batch.rowsImported ?? 0) + (batch.rowsSkipped ?? 0)
}

function parseIssueRows(importBatchId: string, issues: ParseIssue[]) {
  return issues.map((issue, index) => ({
    importBatchId,
    rowNumber: issue.rowNumber ? issue.rowNumber * 1000 + index : -(index + 1),
    rawData: issue.raw ?? {},
    validationErrors: {
      severity: issue.severity,
      code: issue.code,
      message: issue.message,
    },
    status: issue.severity === "error" ? ("failed" as const) : ("needs_review" as const),
    errorMessage: issue.message,
  }))
}

async function replaceParseIssues(importBatchId: string, issues: ParseIssue[]) {
  await prisma.importRow.deleteMany({ where: { importBatchId } })
  const rows = parseIssueRows(importBatchId, issues)
  if (rows.length > 0) {
    await prisma.importRow.createMany({ data: rows })
  }
}

async function logImportFailure(importBatchId: string, error: unknown) {
  await prisma.importLog.create({
    data: {
      importBatchId,
      level: "error",
      event: "failed",
      message: errorMessage(error),
    },
  })
}

async function clearBatchCreatedData(importBatchId: string) {
  await prisma.$transaction([
    prisma.investmentEvent.deleteMany({ where: { importBatchId } }),
    prisma.transaction.deleteMany({ where: { importBatchId } }),
    prisma.importRow.deleteMany({ where: { importBatchId } }),
  ])
}

async function runFullImport({
  batchId,
  parseResult,
  accountId,
  definition,
}: {
  batchId: string
  parseResult: ReturnType<ReturnType<typeof getImportDefinition>["parse"]>
  accountId: string
  definition: ReturnType<typeof getImportDefinition>
}) {
  const result = await runImport({
    parseResult,
    accountId,
    importBatchId: batchId,
    fetchExistingIds: definition.fetchExistingIds,
    saveRows: definition.saveRows,
  })

  await prisma.importBatch.update({
    where: { id: batchId },
    data: {
      rowsTotal: result.rowsTotal,
      rowsImported: result.imported,
      rowsSkipped: result.skipped,
    },
  })
  await replaceParseIssues(batchId, result.parseIssues ?? [])

  return result
}

async function finishImportBatch({
  batchId,
  userId,
  accountId,
  importStartDate,
  definition,
}: {
  batchId: string
  userId: string
  accountId: string
  importStartDate?: Date | null
  definition: ReturnType<typeof getImportDefinition>
}) {
  await definition.postProcess?.(accountId)
  await definition.afterCompleted?.({ userId, accountId, importBatchId: batchId, importStartDate })

  await prisma.importBatch.update({
    where: { id: batchId },
    data: {
      status: "completed",
      completedAt: new Date(),
    },
  })
}

async function completeImportBatches(batchIds: string[]) {
  if (batchIds.length === 0) return
  await prisma.importBatch.updateMany({
    where: { id: { in: batchIds } },
    data: {
      status: "completed",
      completedAt: new Date(),
    },
  })
}

async function failImportBatches(batchIds: string[], error: unknown) {
  await Promise.all(batchIds.map((batchId) => logImportFailure(batchId, error)))
  await prisma.importBatch.updateMany({
    where: { id: { in: batchIds } },
    data: {
      status: "failed",
      completedAt: new Date(),
    },
  })
}

async function runImportGroupJob({
  jobs,
  accountId,
  userId,
  definition,
}: {
  jobs: Array<{
    batchId: string
    parseResult: ReturnType<ReturnType<typeof getImportDefinition>["parse"]>
    importStartDate?: Date | null
  }>
  accountId: string
  userId: string
  definition: ReturnType<typeof getImportDefinition>
}) {
  const batchIds = jobs.map((job) => job.batchId)
  const groupKey = batchIds.join(",")
  if (runningImports.has(groupKey)) return
  runningImports.add(groupKey)

  try {
    await prisma.importBatch.updateMany({
      where: { id: { in: batchIds } },
      data: { status: "processing", completedAt: null },
    })

    for (const job of jobs) {
      await runFullImport({
        batchId: job.batchId,
        parseResult: job.parseResult,
        accountId,
        definition,
      })
    }

    const importStartDate = jobs.reduce<Date | null>((first, job) => {
      if (!job.importStartDate) return first
      return !first || job.importStartDate < first ? job.importStartDate : first
    }, null)

    await definition.postProcess?.(accountId)
    await definition.afterCompleted?.({
      userId,
      accountId,
      importBatchId: jobs[0]?.batchId ?? batchIds[0],
      importStartDate,
    })
    await completeImportBatches(batchIds)
  } catch (error) {
    await failImportBatches(batchIds, error)
  } finally {
    runningImports.delete(groupKey)
  }
}

function scheduleImportGroupJob(args: Parameters<typeof runImportGroupJob>[0]) {
  setTimeout(() => {
    void runImportGroupJob(args)
  }, 0)
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

  const existing = await prisma.importBatch.findFirst({
    where: { userId, accountId, checksum },
    include: {
      _count: {
        select: {
          investmentEvents: true,
          transactions: true,
        },
      },
    },
  })
  if (existing) {
    const storedProcessed = processedRows(existing)
    const parsed = storedProcessed > 0 ? storedProcessed : parseResult.rows.length
    const hasCreatedData = existing._count.investmentEvents > 0 || existing._count.transactions > 0

    if (storedProcessed === 0 && parseResult.rows.length > 0) {
      await prisma.importBatch.update({
        where: { id: existing.id },
        data: { status: "processing", completedAt: null },
      })

      try {
        if (hasCreatedData) await clearBatchCreatedData(existing.id)
        const result = await runFullImport({
          batchId: existing.id,
          parseResult,
          accountId,
          definition,
        })
        await finishImportBatch({
          batchId: existing.id,
          userId,
          accountId,
          importStartDate,
          definition,
        })

        return { ...result, duplicateFile: false }
      } catch (error) {
        await logImportFailure(existing.id, error)
        await prisma.importBatch.update({
          where: { id: existing.id },
          data: {
            status: "failed",
            completedAt: new Date(),
          },
        })
        throw error
      }
    }

    if (existing.status === "failed") {
      await prisma.importBatch.update({
        where: { id: existing.id },
        data: { status: "processing", completedAt: null },
      })

      try {
        await finishImportBatch({
          batchId: existing.id,
          userId,
          accountId,
          importStartDate,
          definition,
        })
      } catch (error) {
        await logImportFailure(existing.id, error)
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
    const result = await runFullImport({
      batchId: batch.id,
      parseResult,
      accountId,
      definition,
    })

    await finishImportBatch({ batchId: batch.id, userId, accountId, importStartDate, definition })

    return result
  } catch (error) {
    await logImportFailure(batch.id, error)
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

export async function importCsvAsync({
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
  const importStartDate = firstParsedDate(parseResult.rows)

  const existing = await prisma.importBatch.findFirst({
    where: { userId, accountId, checksum },
    include: {
      _count: {
        select: {
          investmentEvents: true,
          transactions: true,
        },
      },
    },
  })

  if (existing) {
    const storedProcessed = processedRows(existing)
    const hasCreatedData = existing._count.investmentEvents > 0 || existing._count.transactions > 0
    const canRetryEmpty = storedProcessed === 0 && parseResult.rows.length > 0
    const canRetryFailed = existing.status === "failed"

    if (!canRetryEmpty && !canRetryFailed) {
      return {
        accepted: false,
        duplicateFile: true,
        batchId: existing.id,
        status: existing.status,
        imported: existing.rowsImported ?? 0,
        skipped: existing.rowsSkipped ?? 0,
        duplicates: storedProcessed,
        parsed: storedProcessed || parseResult.rows.length,
        rowsTotal: existing.rowsTotal ?? parseResult.rowsTotal,
        parseIssues: parseResult.issues,
      }
    }

    if (hasCreatedData && canRetryEmpty) await clearBatchCreatedData(existing.id)
    await replaceParseIssues(existing.id, parseResult.issues)
    scheduleImportGroupJob({
      jobs: [{ batchId: existing.id, parseResult, importStartDate }],
      accountId,
      userId,
      definition,
    })

    return {
      accepted: true,
      duplicateFile: false,
      batchId: existing.id,
      status: "processing",
      imported: 0,
      skipped: 0,
      duplicates: 0,
      parsed: parseResult.rows.length,
      rowsTotal: parseResult.rowsTotal,
      parseIssues: parseResult.issues,
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
      rowsTotal: parseResult.rowsTotal,
      rowsImported: 0,
      rowsSkipped: 0,
    },
  })
  await replaceParseIssues(batch.id, parseResult.issues)
  scheduleImportGroupJob({
    jobs: [{ batchId: batch.id, parseResult, importStartDate }],
    accountId,
    userId,
    definition,
  })

  return {
    accepted: true,
    duplicateFile: false,
    batchId: batch.id,
    status: "processing",
    imported: 0,
    skipped: 0,
    duplicates: 0,
    parsed: parseResult.rows.length,
    rowsTotal: parseResult.rowsTotal,
    parseIssues: parseResult.issues,
  }
}

export async function importCsvFilesAsync({
  files,
  accountId,
  userId,
  source,
}: {
  files: Array<{ content: string; filename: string }>
  accountId: string
  userId: string
  source: ImportSource
}) {
  const definition = getImportDefinition(source)
  const results = []
  const jobs: Array<{
    batchId: string
    parseResult: ReturnType<ReturnType<typeof getImportDefinition>["parse"]>
    importStartDate?: Date | null
  }> = []

  for (const file of files) {
    const checksum = crypto.createHash("sha256").update(file.content).digest("hex")
    const parseResult = definition.parse(file.content, accountId)
    const importStartDate = firstParsedDate(parseResult.rows)
    const existing = await prisma.importBatch.findFirst({
      where: { userId, accountId, checksum },
      include: {
        _count: {
          select: {
            investmentEvents: true,
            transactions: true,
          },
        },
      },
    })

    if (existing) {
      const storedProcessed = processedRows(existing)
      const hasCreatedData =
        existing._count.investmentEvents > 0 || existing._count.transactions > 0
      const canRetryEmpty = storedProcessed === 0 && parseResult.rows.length > 0
      const canRetryFailed = existing.status === "failed"

      if (!canRetryEmpty && !canRetryFailed) {
        results.push({
          accepted: false,
          duplicateFile: true,
          batchId: existing.id,
          status: existing.status,
          imported: existing.rowsImported ?? 0,
          skipped: existing.rowsSkipped ?? 0,
          duplicates: storedProcessed,
          parsed: storedProcessed || parseResult.rows.length,
          rowsTotal: existing.rowsTotal ?? parseResult.rowsTotal,
          parseIssues: parseResult.issues,
          filename: file.filename,
        })
        continue
      }

      if (hasCreatedData && canRetryEmpty) await clearBatchCreatedData(existing.id)
      await replaceParseIssues(existing.id, parseResult.issues)
      jobs.push({ batchId: existing.id, parseResult, importStartDate })
      results.push({
        accepted: true,
        duplicateFile: false,
        batchId: existing.id,
        status: "processing",
        imported: 0,
        skipped: 0,
        duplicates: 0,
        parsed: parseResult.rows.length,
        rowsTotal: parseResult.rowsTotal,
        parseIssues: parseResult.issues,
        filename: file.filename,
      })
      continue
    }

    const batch = await prisma.importBatch.create({
      data: {
        checksum,
        filename: file.filename,
        source,
        accountId,
        userId,
        status: "processing",
        rowsTotal: parseResult.rowsTotal,
        rowsImported: 0,
        rowsSkipped: 0,
      },
    })
    await replaceParseIssues(batch.id, parseResult.issues)
    jobs.push({ batchId: batch.id, parseResult, importStartDate })
    results.push({
      accepted: true,
      duplicateFile: false,
      batchId: batch.id,
      status: "processing",
      imported: 0,
      skipped: 0,
      duplicates: 0,
      parsed: parseResult.rows.length,
      rowsTotal: parseResult.rowsTotal,
      parseIssues: parseResult.issues,
      filename: file.filename,
    })
  }

  if (jobs.length > 0) {
    scheduleImportGroupJob({ jobs, accountId, userId, definition })
  }

  return {
    accepted: jobs.length > 0,
    batchIds: results.map((result) => result.batchId),
    files: results,
  }
}
