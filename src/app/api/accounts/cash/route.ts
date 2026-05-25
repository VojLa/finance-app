import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma, toNum } from "@/lib/prisma"
import { getCzkRates, toCzk } from "@/modules/portfolio/rates/service"
import type { CashSummary } from "@/types"

export async function GET() {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const [accounts, czkRates] = await Promise.all([
    prisma.account.findMany({
      where: { userId: session.user.id },
      orderBy: { createdAt: "asc" },
    }),
    getCzkRates(),
  ])

  const cashMap: Record<string, Record<string, number>> = {}

  const investmentAccountIds = accounts
    .filter((a) => ["broker", "exchange", "crypto_wallet"].includes(a.type))
    .map((a) => a.id)

  const bankAccountIds = accounts.filter((a) => ["bank", "cash"].includes(a.type)).map((a) => a.id)

  if (investmentAccountIds.length > 0) {
    const txs = await prisma.investmentTransaction.findMany({
      where: {
        accountId: { in: investmentAccountIds },
        type: {
          in: ["deposit", "withdrawal", "buy", "sell", "dividend", "interest", "staking_reward"],
        },
      },
      select: { accountId: true, type: true, totalAmount: true, totalCurrency: true },
    })

    for (const tx of txs) {
      if (tx.totalAmount == null || !tx.totalCurrency) continue
      if (!cashMap[tx.accountId]) cashMap[tx.accountId] = {}

      const amount = toNum(tx.totalAmount)
      let delta: number
      switch (tx.type) {
        case "deposit":
        case "sell":
        case "dividend":
        case "interest":
        case "staking_reward":
          delta = Math.abs(amount)
          break
        case "withdrawal":
        case "buy":
          delta = -Math.abs(amount)
          break
        default:
          continue
      }

      cashMap[tx.accountId][tx.totalCurrency] =
        (cashMap[tx.accountId][tx.totalCurrency] ?? 0) + delta
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
