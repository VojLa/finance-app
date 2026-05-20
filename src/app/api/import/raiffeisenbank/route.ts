import { NextRequest, NextResponse } from "next/server"

import { autoCategorize } from "@/lib/categorize"
import { prisma } from "@/lib/prisma"
import { parseRaiffeisenbank } from "@/imports/raiffeisenbank/parser"
import {
  getImportContext,
  handleImportError,
  writeImportLog,
} from "@/imports/utils/api"

function isString(value: string | null): value is string {
  return Boolean(value)
}

export async function POST(req: NextRequest) {
  try {
    const context = await getImportContext(req)

    if (!context.ok) {
      return context.response
    }

    const csvText = await context.file.text()
    const rows = parseRaiffeisenbank(csvText, context.accountId)
    const refs = rows.map(row => row.transactionRef).filter(Boolean)

    const existingRefs =
      refs.length > 0
        ? new Set(
            (
              await prisma.transaction.findMany({
                where: {
                  accountId: context.accountId,
                  transactionRef: {
                    in: refs,
                  },
                },
                select: {
                  transactionRef: true,
                },
              })
            )
              .map(row => row.transactionRef)
              .filter(isString)
          )
        : new Set<string>()

    const newRows = rows.filter(row => !existingRefs.has(row.transactionRef))

    if (newRows.length > 0) {
      await prisma.transaction.createMany({
        data: newRows.map(row => ({
          date: row.date,
          amount: row.amount,
          currency: row.currency,
          type: row.type,
          description: row.description || null,
          counterparty: row.counterparty || null,
          transactionRef: row.transactionRef || null,
          accountId: row.accountId,
        })),
      })

      await autoCategorize(context.accountId)
    }

    await writeImportLog({
      filename: context.file.name,
      source: "raiffeisenbank",
      rowsImported: newRows.length,
      rowsSkipped: rows.length - newRows.length,
      accountId: context.accountId,
    })

    return NextResponse.json({
      imported: newRows.length,
      skipped: rows.length - newRows.length,
      parsed: rows.length,
    })
  } catch (error) {
    return handleImportError(error, "Raiffeisenbank import error")
  }
}
