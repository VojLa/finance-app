import { describe, expect, it } from "vitest"
import {
  OperationalDashboardContractError,
  buildOperationalDashboardData,
} from "./operational-dashboard-model"

const legacyPayload = {
  summary: {
    cashValueCzk: 700,
    portfolioValueCzk: 800,
    liabilitiesValueCzk: -100,
    netWorthCzk: 1400,
    currentMonthIncomeCzk: "1200.000000",
    currentMonthExpenseCzk: "450.000000",
    currentMonthNetCzk: "750.000000",
  },
  accountBalances: [{ accountId: "must-not-pass-through", totalCzk: 123 }],
  budget: {
    id: "budget-1",
    month: 7,
    year: 2026,
    limitCzk: "1000.000000",
    spentCzk: "450.000000",
    remainingCzk: "550.000000",
    progressPct: "45.0000",
    items: [
      {
        id: "item-1",
        categoryId: "category-1",
        name: "Jídlo",
        icon: null,
        color: "#00aa00",
        limitCzk: "500.000000",
        spentCzk: "200.000000",
        remainingCzk: "300.000000",
        progressPct: "40.0000",
        isOver: false,
      },
    ],
  },
  expenseByCategory: [
    {
      categoryId: "category-1",
      name: "Jídlo",
      icon: null,
      color: "#00aa00",
      amountCzk: "200.000000",
    },
  ],
  monthlyTrends: [
    {
      month: "2026-07",
      label: "čvc",
      incomeCzk: "1200.000000",
      expenseCzk: "450.000000",
      netCzk: "750.000000",
    },
  ],
  recentTransactions: [
    {
      id: "transaction-1",
      date: "2026-07-30",
      amount: "200.000000",
      amountCzk: "200.000000",
      currency: "CZK",
      type: "expense",
      description: "Oběd",
      counterparty: null,
      accountName: "Běžný účet",
      categoryName: "Jídlo",
      categoryIcon: null,
    },
  ],
}

describe("operational dashboard model", () => {
  it("selects only current-month and operational fields from the legacy payload", () => {
    const result = buildOperationalDashboardData(legacyPayload)

    expect(result.currentMonth).toEqual({ income: 1200, expenses: 450, net: 750 })
    expect(result.budget?.items).toHaveLength(1)
    expect(result.expenseByCategory).toHaveLength(1)
    expect(result.monthlyTrends).toHaveLength(1)
    expect(result.recentTransactions).toHaveLength(1)
    expect(Object.keys(result)).toEqual([
      "currentMonth",
      "budget",
      "expenseByCategory",
      "monthlyTrends",
      "recentTransactions",
    ])
    expect(JSON.stringify(result)).not.toMatch(
      /cashValueCzk|portfolioValueCzk|liabilitiesValueCzk|netWorthCzk|accountBalances/
    )
  })

  it("fails closed on malformed operational data", () => {
    expect(() =>
      buildOperationalDashboardData({
        ...legacyPayload,
        summary: { ...legacyPayload.summary, currentMonthNetCzk: "750" },
      })
    ).toThrow(OperationalDashboardContractError)
  })

  it("is deterministic and does not mutate the legacy response", () => {
    const before = structuredClone(legacyPayload)
    expect(buildOperationalDashboardData(legacyPayload)).toEqual(
      buildOperationalDashboardData(legacyPayload)
    )
    expect(legacyPayload).toEqual(before)
  })
})
