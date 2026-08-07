import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

import { buildSnapshotDashboardModel } from "@/modules/dashboard/snapshot-dashboard-model"
import {
  buildPortfolioPageModel,
  selectPortfolioAccountView,
} from "@/modules/portfolio/snapshot-page-model"
import { dashboardSnapshotFixture } from "@/test/dashboard-snapshot-fixture"
import { portfolioSnapshotFixture } from "@/test/portfolio-snapshot-fixture"

const ROOT = process.cwd()

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

describe("version 0.1 clean main browser call graph", () => {
  it("keeps accounts and all required imports on authenticated Python adapters", async () => {
    const accountRoute = await source("src/app/api/accounts/route.ts")
    const accountAdapter = await source("src/modules/accounts/server/account-api.ts")
    const importRoute = await source("src/app/api/import/route.ts")
    const importHandler = await source("src/modules/imports/python/import-route.ts")
    const importAdapter = await source("src/modules/imports/python/import-api.ts")
    const active = `${accountRoute}\n${accountAdapter}\n${importRoute}\n${importHandler}\n${importAdapter}`

    expect(accountRoute).toContain("getServerSession")
    expect(accountRoute).toContain("createAccount")
    expect(accountAdapter).toContain('client.POST("/api/v1/accounts"')
    expect(importRoute).toContain("handleImportPost")
    expect(importHandler).toContain("runImportCanonicalWorkflow")
    expect(importHandler).toContain("finalizeImportBatches")
    for (const stage of [
      "createImportBatch",
      "uploadImportFile",
      "parseImportBatch",
      "normalizeImportBatch",
      "deduplicateImportBatch",
      "classifyImportBatch",
      "postImportBatch",
    ]) {
      expect(importAdapter).toContain(stage)
    }
    expect(importHandler).toContain("isPythonImportSource")
    expect(active).toContain("createAuthenticatedPythonTransport")
    expect(active).not.toMatch(/@\/lib\/prisma|\bprisma\.|importCsvFilesAsync|papaparse/)
  })

  it("keeps portfolio, dashboard and history on exact snapshot-backed workflows", async () => {
    const workflow = await source("src/modules/python-api/server/snapshot-workflow.ts")
    const portfolioRoute = await source("src/app/api/snapshot-workflow/portfolio/route.ts")
    const dashboardRoute = await source("src/app/api/snapshot-workflow/dashboard/route.ts")
    const historyRoute = await source("src/app/api/portfolio/history/route.ts")
    const historyAdapter = await source("src/modules/python-api/server/portfolio-history.ts")
    const active = `${workflow}\n${portfolioRoute}\n${dashboardRoute}\n${historyRoute}\n${historyAdapter}`

    expect(portfolioRoute).toContain("runPortfolioSnapshotWorkflow")
    expect(dashboardRoute).toContain("runDashboardSnapshotWorkflow")
    expect(workflow).toContain("recalculateSnapshotRefresh")
    expect(workflow).toContain("readPortfolioSnapshot")
    expect(workflow).toContain("readDashboardSnapshot")
    expect(historyRoute).toContain("readSnapshotBackedPortfolioHistory")
    expect(historyAdapter).toContain('client.GET("/api/v1/portfolio/history"')
    expect(active).not.toMatch(
      /@\/lib\/prisma|@\/modules\/snapshots|\/api\/rates|getPortfolioSnapshotHistory/
    )
  })

  it("preserves server-owned CZK values and original-currency evidence in page models", () => {
    const portfolio = portfolioSnapshotFixture()
    portfolio.currency = "CZK"
    const page = buildPortfolioPageModel(portfolio)
    const selected = selectPortfolioAccountView(page, "account-b")
    const dashboard = buildSnapshotDashboardModel(dashboardSnapshotFixture)

    expect(page.currency).toBe("CZK")
    expect(page.aggregate.summary).toBe(portfolio.summary)
    expect(selected?.summary).toBe(portfolio.accounts[1]?.summary)
    expect(page.aggregate.summary.cashByCurrency.map((item) => item.currency)).toEqual([
      "CZK",
      "EUR",
      "USD",
    ])
    expect(page.aggregate.summary.cashByCurrency[2]?.amount).toBe("-50.000000")
    expect(dashboard.currency).toBe("CZK")
    expect(dashboard.summary).toBe(dashboardSnapshotFixture.summary)
  })

  it("contains no new CZK target hardcoding in production snapshot planning or APIs", async () => {
    const production = (
      await Promise.all(
        [
          "backend/python/app/modules/market_data/requirements.py",
          "backend/python/app/modules/snapshot_refresh/plan.py",
          "backend/python/app/modules/snapshot_refresh/market_backed_service.py",
          "backend/python/app/modules/snapshot_refresh/manual_service.py",
          "backend/python/app/modules/snapshot_refresh/api.py",
          "backend/python/app/modules/portfolio_snapshot/api.py",
          "backend/python/app/modules/dashboard_snapshot/api.py",
          "backend/python/app/modules/portfolio_history/api.py",
        ].map(source)
      )
    ).join("\n")

    expect(production).not.toMatch(/(?:output_currency|base_currency|currency)\s*=\s*["']CZK["']/)
  })
})
