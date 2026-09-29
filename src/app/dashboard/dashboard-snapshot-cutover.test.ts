import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

describe("dashboard snapshot cutover boundaries", () => {
  it("uses the workflow as the sole financial source and legacy dashboard only for operations", async () => {
    const page = await source("src/app/dashboard/page.tsx")
    const snapshotClient = await source("src/modules/dashboard/snapshot-dashboard-client.ts")
    const operationalContract = await source(
      "src/modules/dashboard/operational-dashboard-contract.ts"
    )
    const operationalClient = await source("src/modules/dashboard/operational-dashboard-client.ts")

    expect(snapshotClient).toContain("/api/snapshot-workflow/dashboard")
    expect(snapshotClient).toContain('method: "POST"')
    expect(snapshotClient).not.toMatch(/\bbody\s*:/)
    expect(operationalClient).toContain("/api/dashboard")
    expect(operationalClient).toContain('method: "GET"')
    expect(page).not.toMatch(/\bfetch\s*\(/)
    expect(page).not.toMatch(
      /cashValueCzk|portfolioValueCzk|liabilitiesValueCzk|netWorthCzk|accountBalances/
    )
    expect(page).toContain("financialState.current.isStale")
    expect(page).toContain("financialState.current.valuationTimestamp")
    expect(page).toContain("Ceny jsou starší než 30 minut")
    expect(operationalContract).not.toMatch(
      /cashValueCzk|portfolioValueCzk|liabilitiesValueCzk|netWorthCzk|accountBalances/
    )
  })

  it("keeps every forbidden legacy financial field out of page production modules", async () => {
    const productionFiles = [
      "src/app/dashboard/page.tsx",
      "src/modules/dashboard/operational-dashboard-client.ts",
      "src/modules/dashboard/operational-dashboard-contract.ts",
      "src/modules/dashboard/operational-dashboard-model.ts",
      "src/modules/dashboard/snapshot-dashboard-client.ts",
      "src/modules/dashboard/snapshot-dashboard-model.ts",
      "src/modules/dashboard/OperationalDashboardSections.tsx",
      "src/modules/dashboard/SnapshotSummaryCards.tsx",
      "src/modules/dashboard/SnapshotAccountCards.tsx",
      "src/modules/dashboard/SnapshotAssetAllocationChart.tsx",
      "src/modules/dashboard/SnapshotTopPositions.tsx",
    ]
    const forbidden =
      /\b(?:cashValueCzk|portfolioValueCzk|liabilitiesValueCzk|netWorthCzk|accountBalances|totalCzk|balances)\b/

    for (const file of productionFiles) {
      expect(await source(file), file).not.toMatch(forbidden)
    }
  })

  it("allows one documented presentation-only Decimal conversion at the chart leaf", async () => {
    const productionFiles = [
      "src/app/dashboard/page.tsx",
      "src/modules/dashboard/snapshot-dashboard-client.ts",
      "src/modules/dashboard/snapshot-dashboard-model.ts",
      "src/modules/dashboard/SnapshotSummaryCards.tsx",
      "src/modules/dashboard/SnapshotAccountCards.tsx",
      "src/modules/dashboard/SnapshotTopPositions.tsx",
    ]
    const allocation = await source("src/modules/dashboard/SnapshotAssetAllocationChart.tsx")

    for (const file of productionFiles) {
      const content = await source(file)
      expect(content, file).not.toMatch(/\b(?:Number|parseFloat|parseInt)\s*\(/)
      expect(content, file).not.toMatch(/\bMath\./)
      expect(content, file).not.toContain(".toFixed(")
      expect(content, file).not.toContain(".sort(")
    }
    expect(allocation.match(/\bNumber\s*\(/g)).toHaveLength(1)
    expect(allocation).toContain("Presentation-only Decimal conversion required by Recharts")
    expect(allocation).not.toMatch(/\b(?:parseFloat|parseInt|Math)\b/)
    expect(allocation).not.toContain(".toFixed(")
  })

  it("keeps account cards, allocations, and top positions server-owned", async () => {
    const model = await source("src/modules/dashboard/snapshot-dashboard-model.ts")
    const accounts = await source("src/modules/dashboard/SnapshotAccountCards.tsx")
    const allocation = await source("src/modules/dashboard/SnapshotAssetAllocationChart.tsx")
    const positions = await source("src/modules/dashboard/SnapshotTopPositions.tsx")
    const content = `${model}\n${accounts}\n${allocation}\n${positions}`

    expect(content).not.toMatch(/\b(?:Prisma|latest|current snapshot|FX|live.price)\b/i)
    expect(content).not.toContain(".sort(")
    expect(content).not.toContain(".reduce(")
    expect(content).not.toMatch(/account discovery/i)
    expect(positions).toContain("model.topPositions.map")
    expect(allocation).toContain("model.assetTypeAllocations.map")
  })

  it("keeps dashboard and portfolio routes on the Python publication boundary", async () => {
    const portfolioPage = await source("src/app/portfolio/page.tsx")
    expect(portfolioPage).toContain("requestPortfolioPageState")
    expect(portfolioPage).toContain("startPortfolioHistoryRequest")
    expect(portfolioPage).not.toMatch(/@\/lib\/prisma|getCzkRates|toCzk|accountAccess/)

    const route = await source("src/app/api/dashboard/route.ts")
    expect(route).toContain("createPythonOperationalDashboardApi")
    expect(route).not.toMatch(/@\/lib\/prisma|getCzkRates|toCzk|accountAccess/)
    const portfolioRoute = await source("src/app/api/snapshot-workflow/portfolio/route.ts")
    const dashboardRoute = await source("src/app/api/snapshot-workflow/dashboard/route.ts")
    expect(portfolioRoute).toContain("runPortfolioSnapshotWorkflow")
    expect(dashboardRoute).toContain("runDashboardSnapshotWorkflow")
    expect(`${portfolioRoute}\n${dashboardRoute}`).not.toMatch(
      /@\/lib\/prisma|getCzkRates|toCzk|accountAccess/
    )
    const generated = await source("src/generated/python-api.ts")
    expect(generated).toContain("OperationalDashboardResponse")
    expect(generated).toContain("DashboardSnapshotResponse")
  })
})
