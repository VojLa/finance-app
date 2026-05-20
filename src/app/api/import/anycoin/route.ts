import { NextRequest, NextResponse } from "next/server"

import { prisma } from "@/lib/prisma"
import { recalculateHoldings } from "@/lib/portfolio"
import { parseAnycoin } from "@/imports/anycoin/parser"
import {
  getImportContext,
  handleImportError,
  writeImportLog,
} from "@/imports/utils/api"

function isString(value: string | null | undefined): value is string {
  return Boolean(value)
}

export async function POST(req: NextRequest) {
  try {
    const context = await getImportContext(req)

    if (!context.ok) {
      return context.response
    }

    const csvText = await context.file.text()
    const transactions = parseAnycoin(csvText, context.accountId)
    const externalIds = transactions.map(row => row.externalId).filter(isString)

    const existingIds =
      externalIds.length > 0
        ? new Set(
            (
              await prisma.investmentTransaction.findMany({
                where: {
                  accountId: context.accountId,
                  externalId: {
                    in: externalIds,
                  },
                },
                select: {
                  externalId: true,
                },
              })
            )
              .map(row => row.externalId)
              .filter(isString)
          )
        : new Set<string>()

    const newTransactions = transactions.filter(
      transaction => !transaction.externalId || !existingIds.has(transaction.externalId)
    )

    let warnings: { symbol: string; quantity: number }[] = []

    if (newTransactions.length > 0) {
      await prisma.investmentTransaction.createMany({
        data: newTransactions,
      })

      const result = await recalculateHoldings(context.accountId)
      warnings = result.warnings
    }

    await writeImportLog({
      filename: context.file.name,
      source: "anycoin",
      rowsImported: newTransactions.length,
      rowsSkipped: transactions.length - newTransactions.length,
      accountId: context.accountId,
    })

    return NextResponse.json({
      imported: newTransactions.length,
      skipped: transactions.length - newTransactions.length,
      parsed: transactions.length,
      warnings,
    })
  } catch (error) {
    return handleImportError(error, "Anycoin import error")
  }
}
