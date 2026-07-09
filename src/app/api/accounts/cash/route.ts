import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma, toNum } from "@/lib/prisma"
import { getCzkRates, toCzk } from "@/modules/portfolio/rates/service"
import { getAccessibleAccountIds } from "@/lib/accountAccess"
import type { CashSummary } from "@/types"

export async function GET() {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const accessibleIds = await getAccessibleAccountIds(session.user.id, "viewer")
  const [accounts, czkRates] = await Promise.all([
    prisma.account.findMany({
      where: { id: { in: accessibleIds } },
      orderBy: { createdAt: "asc" },
    }),
    getCzkRates(),
  ])

  const cashMap: Record<string, Record<string, number>> = {}

  const investmentAccountIds = accounts
    .filter((a) => ["broker", "exchange", "crypto_wallet"].includes(a.type))
    .map((a) => a.id)

  const bankAccountIds = accounts
    .filter((a) => ["bank", "cash", "savings"].includes(a.type))
    .map((a) => a.id)

  if (investmentAccountIds.length > 0) {
    const txs = await prisma.investmentMovement.findMany({
      where: {
        accountId: { in: investmentAccountIds },
        kind: { in: ["cash", "fee", "tax"] },
        event: { deletedAt: null, archivedAt: null },
      },
      select: { accountId: true, direction: true, quantity: true, currency: true },
    })

    for (const tx of txs) {
      if (!cashMap[tx.accountId]) cashMap[tx.accountId] = {}

      const amount = Math.abs(toNum(tx.quantity))
      const delta = tx.direction === "in" ? amount : -amount

      cashMap[tx.accountId][tx.currency] = (cashMap[tx.accountId][tx.currency] ?? 0) + delta
    }
  }

  if (bankAccountIds.length > 0) {
    const txs = await prisma.transaction.findMany({
      where: {
        accountId: { in: bankAccountIds },
        type: { in: ["income", "expense"] },
      },
      select: { accountId: true, type: true, amount: true, currency: true },
    })

    for (const tx of txs) {
      if (!cashMap[tx.accountId]) cashMap[tx.accountId] = {}
      const amount = toNum(tx.amount)
      const delta = tx.type === "income" ? amount : -amount
      cashMap[tx.accountId][tx.currency] = (cashMap[tx.accountId][tx.currency] ?? 0) + delta
    }
  }

  let totalCashCzk = 0
  const accountResults = accounts.map((account) => {
    const balances = Object.entries(cashMap[account.id] ?? {})
      .filter(([, amount]) => Math.abs(amount) >= 0.01)
      .map(([currency, amount]) => ({
        currency,
        amount,
        amountCzk: toCzk(amount, currency, czkRates),
      }))
      .sort((a, b) => Math.abs(b.amountCzk) - Math.abs(a.amountCzk))

    const accountTotalCzk = balances.reduce((sum, b) => sum + b.amountCzk, 0)
    totalCashCzk += accountTotalCzk

    return {
      accountId: account.id,
      accountName: account.name,
      accountType: account.type as string,
      color: account.color,
      balances,
      totalCzk: accountTotalCzk,
    }
  })

  const summary: CashSummary = {
    accounts: accountResults.filter((a) => a.balances.length > 0),
    totalCashCzk,
    czkRates,
  }

  return NextResponse.json(summary)
}
