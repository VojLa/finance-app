import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

describe("R11-F budget and operational dashboard cutover", () => {
  it("keeps budget and dashboard Next routes transport-only", async () => {
    const budget = await source("src/app/api/budget/route.ts")
    const dashboard = await source("src/app/api/dashboard/route.ts")
    expect(budget).toContain("createPythonBudgetApi")
    expect(dashboard).toContain("createPythonOperationalDashboardApi")
    for (const content of [budget, dashboard]) {
      expect(content).toContain("getServerSession(authOptions)")
      expect(content).not.toMatch(/@\/lib\/prisma|prisma\.|accountAccess|getCzkRates|toCzk/)
      expect(content).not.toMatch(/yahoo|twelve|coingecko|fetch\(/i)
    }
  })

  it("uses generated contracts and preserves exact budget input strings", async () => {
    const page = await source("src/app/budget/page.tsx")
    const contract = await source("src/modules/budgets/budget-contract.ts")
    expect(contract).toContain('components["schemas"]["BudgetProgressResponse"]')
    expect(page).toContain("amount: newAmount")
    expect(page).toContain("requestBudget")
    expect(page).toContain("saveBudget")
    expect(page).not.toMatch(/parseFloat|@\/lib\/prisma|fetch\(/)
  })

  it("keeps providers, financial summary and writes out of operational dashboard", async () => {
    const backend = (
      await Promise.all(
        [
          "backend/python/app/modules/operational_dashboard/api.py",
          "backend/python/app/modules/operational_dashboard/service.py",
          "backend/python/app/modules/operational_dashboard/repository.py",
        ].map(source)
      )
    ).join("\n")
    expect(backend).not.toMatch(/market_data|provider|PriceSnapshot|ExchangeRate|HoldingModel/)
    expect(backend).not.toMatch(/session\.add|session\.delete|INSERT|UPDATE|DELETE/)
    expect(backend).not.toMatch(/cash_value|portfolio_value|net_worth|account_balances/)
  })

  it("publishes exact strings for every operational money field", async () => {
    const generated = await source("src/generated/python-api.ts")
    const start = generated.indexOf("OperationalDashboardResponse:")
    const responseSchemas = generated.slice(start - 5000, start + 1200)
    expect(responseSchemas).toContain("OperationalDashboardResponse")
    expect(responseSchemas).toMatch(/amountCzk: string/)
    expect(generated).toMatch(/currentMonthIncomeCzk: string/)
  })
})
