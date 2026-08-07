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

function matrixRows(markdown: string): string[][] {
  return markdown
    .split(/\r?\n/)
    .filter((line) => /^\| [A-Z][A-Z0-9-]+\s+\|/.test(line) && !line.startsWith("| ID "))
    .map((line) =>
      line
        .replace(/^\||\|$/g, "")
        .split("|")
        .map((cell) => cell.trim())
    )
}

describe("version 0.1 R9 browser and release acceptance", () => {
  it("reuses all 87 historical requirement identities and scope texts", async () => {
    const historical = matrixRows(await source("ChatGPT/audits/0.1-requirement-matrix.md"))
    const current = matrixRows(await source("ChatGPT/audits/0.1-r9-requirement-matrix.md"))

    expect(historical).toHaveLength(87)
    expect(current).toHaveLength(87)
    expect(current.map((row) => row.slice(0, 3))).toEqual(historical.map((row) => row.slice(0, 3)))
    expect(new Set(current.map((row) => row[0])).size).toBe(87)
    expect(current.find((row) => row[0] === "SCOPE-02")?.[5]).toBe("OUT_OF_SCOPE")
  })

  it("keeps accounts and imports on one authenticated Python adapter path", async () => {
    const accountRoute = await source("src/app/api/accounts/route.ts")
    const accountAdapter = await source("src/modules/accounts/server/account-api.ts")
    const importRoute = await source("src/app/api/import/route.ts")
    const importHandler = await source("src/modules/imports/python/import-route.ts")
    const importAdapter = await source("src/modules/imports/python/import-api.ts")
    const transport = await source("src/modules/python-api/server/transport.ts")
    const active = [
      accountRoute,
      accountAdapter,
      importRoute,
      importHandler,
      importAdapter,
      transport,
    ].join("\n")

    expect(accountRoute).toContain("getServerSession")
    expect(accountRoute).toContain("createAccount")
    expect(accountAdapter).toContain('client.POST("/api/v1/accounts"')
    expect(importRoute).toContain("handleImportPost")
    expect(importHandler).toContain("runImportWorkflow")
    for (const stage of [
      "createImportBatch",
      "uploadImportFile",
      "parseImportBatch",
      "normalizeImportBatch",
      "deduplicateImportBatch",
      "classifyImportBatch",
      "postImportBatch",
      "getImportBatch",
    ]) {
      expect(importAdapter).toContain(stage)
    }
    expect(transport).toContain("issueInternalToken")
    expect(transport).toContain('cache: "no-store"')
    expect(transport).toContain("Authorization: `Bearer ${token}`")
    expect(active).not.toMatch(/@\/lib\/prisma|\bprisma\.|importCsvFilesAsync|papaparse|Cookie:/)
  })

  it("keeps current portfolio, dashboard and history on exact Python snapshot reads", async () => {
    const workflow = await source("src/modules/python-api/server/snapshot-workflow.ts")
    const portfolioRoute = await source("src/app/api/snapshot-workflow/portfolio/route.ts")
    const dashboardRoute = await source("src/app/api/snapshot-workflow/dashboard/route.ts")
    const historyRoute = await source("src/app/api/portfolio/history/route.ts")
    const historyAdapter = await source("src/modules/python-api/server/portfolio-history.ts")
    const portfolioPage = await source("src/app/portfolio/page.tsx")
    const dashboardPage = await source("src/app/dashboard/page.tsx")
    const active = [
      workflow,
      portfolioRoute,
      dashboardRoute,
      historyRoute,
      historyAdapter,
      portfolioPage,
      dashboardPage,
    ].join("\n")

    expect(portfolioRoute).toContain("runPortfolioSnapshotWorkflow")
    expect(dashboardRoute).toContain("runDashboardSnapshotWorkflow")
    expect(workflow).toContain("recalculateSnapshotRefresh")
    expect(workflow).toContain("readPortfolioSnapshot")
    expect(workflow).toContain("readDashboardSnapshot")
    expect(historyRoute).toContain("readSnapshotBackedPortfolioHistory")
    expect(historyAdapter).toContain('client.GET("/api/v1/portfolio/history"')
    expect(portfolioPage).toContain("requestPortfolioPageState")
    expect(portfolioPage).toContain("startPortfolioHistoryRequest")
    expect(dashboardPage).toContain("requestDashboardFinancialState")
    expect(active).not.toMatch(
      /@\/lib\/prisma|@\/modules\/snapshots|\/api\/rates|getPortfolioSnapshotHistory/
    )
  })

  it("preserves exact server summaries and limits Number conversion to chart leaves", async () => {
    const portfolio = portfolioSnapshotFixture()
    const model = buildPortfolioPageModel(portfolio)
    const selected = selectPortfolioAccountView(model, "account-b")
    const dashboardFixture = dashboardSnapshotFixture
    const dashboard = buildSnapshotDashboardModel(dashboardFixture)
    const pageModelSource = await source("src/modules/portfolio/snapshot-page-model.ts")
    const dashboardModelSource = await source("src/modules/dashboard/snapshot-dashboard-model.ts")
    const portfolioChart = await source("src/modules/portfolio/SnapshotAllocationPie.tsx")
    const dashboardChart = await source("src/modules/dashboard/SnapshotAssetAllocationChart.tsx")

    expect(model.aggregate.summary).toBe(portfolio.summary)
    expect(selected?.summary).toBe(portfolio.accounts[1]?.summary)
    expect(model.aggregate.summary.cashByCurrency.map((item) => item.currency)).toEqual([
      "CZK",
      "EUR",
      "USD",
    ])
    expect(model.aggregate.summary.cashByCurrency[2]?.amount).toBe("-50.000000")
    expect(dashboard.summary).toBe(dashboardFixture.summary)
    expect(`${pageModelSource}\n${dashboardModelSource}`).not.toMatch(
      /Number\(|parseFloat\(|parseInt\(|Math\.|\.toFixed\(|\.reduce\(|\.sort\(/
    )
    expect(portfolioChart).toContain("function toChartNumber")
    expect(portfolioChart).toContain("Number(value)")
    expect(dashboardChart).toContain("function toChartNumber")
    expect(dashboardChart).toContain("Number(value)")
  })

  it("classifies retained legacy routes without using them in the main financial flow", async () => {
    const accountPage = await source("src/app/accounts/page.tsx")
    const importPage = await source("src/app/import/page.tsx")
    const portfolioPage = await source("src/app/portfolio/page.tsx")
    const dashboardPage = await source("src/app/dashboard/page.tsx")
    const active = `${accountPage}\n${importPage}\n${portfolioPage}\n${dashboardPage}`
    const operationalDashboard = await source(
      "src/modules/dashboard/operational-dashboard-client.ts"
    )

    expect(accountPage).toContain("requestAccounts")
    expect(importPage).toContain("requestImport")
    expect(portfolioPage).toContain("requestPortfolioPageState")
    expect(dashboardPage).toContain("requestDashboardFinancialState")
    expect(operationalDashboard).toContain("/api/dashboard")
    expect(active).not.toMatch(
      /\/api\/portfolio(?:["'?])|\/api\/rates|\/api\/accounts\/cash|importCsvFilesAsync|@\/lib\/prisma/
    )
  })

  it("keeps the Frontend workflow complete, clean and sensitive to R9 changes", async () => {
    const workflow = await source(".github/workflows/frontend.yml")

    for (const pathFilter of ['- "src/**"', '- "prisma/**"', '- "package.json"']) {
      expect(workflow).toContain(pathFilter)
    }
    for (const command of [
      "npm ci",
      "npm run db:generate",
      "npm run api:python:check",
      "npm test",
      "npm run lint",
      "npx tsc --noEmit --incremental false",
      "npm run db:validate",
      "git diff --check",
      'test -z "$(git status --porcelain)"',
    ]) {
      expect(workflow).toContain(command)
    }
    expect(workflow).not.toContain("continue-on-error")
    expect(workflow).not.toContain("|| true")
    expect(workflow).not.toMatch(/next dev|npm audit fix|auto-merge/i)
  })

  it("records only the post-audit internal architecture milestone", async () => {
    const historical = await source("ChatGPT/audits/0.1-final-acceptance.md")
    const remediation = await source("ChatGPT/steps/0.1-remediation.md")
    const roadmap = await source("!planning/product/02-roadmap.md")
    const report = await source("ChatGPT/audits/0.1-r9-final-acceptance.md")

    expect(historical).toContain("## Final verdict")
    expect(historical).toContain("**NOT READY**")
    expect(remediation).toContain("0.1-R9 — repeat final acceptance audit: implemented — PASS")
    expect(remediation).toContain("Version 0.1 — complete")
    expect(report).toContain("VERSION 0.1 FINAL VERDICT: PASS")
    expect(report).toContain("internal architecture MVP")
    expect(report.toLowerCase()).not.toContain("is production ready")
    expect(report.toLowerCase()).not.toContain("is a public beta")
    expect(roadmap).toContain("completed technical milestone")
  })

  it("contains no historical Git-object dependency", async () => {
    const current = await source("src/app/version-0-1-r9-final-acceptance.test.ts")

    expect(current).not.toContain(["exec", "File", "Sync"].join(""))
    expect(current).not.toContain(["git", " show"].join(""))
    expect(current).not.toMatch(/\b[0-9a-f]{40}\b/)
  })
})
