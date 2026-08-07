import { createHash } from "node:crypto"
import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

async function sha256(relativePath: string): Promise<string> {
  return createHash("sha256")
    .update(await readFile(path.join(ROOT, relativePath)))
    .digest("hex")
}

describe("portfolio snapshot page cutover boundaries", () => {
  it("uses only the snapshot workflow as the current portfolio source", async () => {
    const page = await source("src/app/portfolio/page.tsx")
    const client = await source("src/modules/portfolio/snapshot-page-client.ts")
    const currentSource = `${page}\n${client}`

    expect(currentSource).toContain("/api/snapshot-workflow/portfolio")
    expect(page).not.toContain('fetch("/api/portfolio')
    expect(page).not.toContain("/api/portfolio?")
    expect(page).not.toContain("api/rates?refresh=true")
    expect(page).not.toContain("/api/portfolio/snapshots/recalculate")
    expect(page).not.toContain("cashAmountCzk")
    expect(page).not.toContain("totalValue - totalCost")
    expect(page).not.toContain("pnl / cost")
    expect(page).not.toContain("latestHistoryPoint")
    expect(page).not.toMatch(/\b(?:Prisma|YAHOO|FX lookup)\b/)
    expect(page).toContain("view.summary.netDepositsValue")
    expect(page).toContain("view.summary.cashByCurrency")
    expect(page).toContain("view.summary.netDepositsByCurrency")
    expect(page).toContain("<SnapshotCurrencyBreakdown")
    expect(client).toContain('method: "POST"')
    expect(client).not.toMatch(/\bbody\s*:/)
    expect(client).not.toContain("accountId")
  })

  it("uses strict Python snapshot history without changing current cards and positions", async () => {
    const page = await source("src/app/portfolio/page.tsx")
    const historyClient = await source("src/modules/portfolio/snapshot-history-client.ts")
    const historyContract = await source("src/modules/portfolio/snapshot-history-contract.ts")
    const route = await source("src/app/api/portfolio/history/route.ts")
    const transport = await source("src/modules/python-api/server/portfolio-history.ts")

    expect(historyClient).toContain("/api/portfolio/history?")
    expect(historyClient).not.toContain("accountId")
    expect(historyClient).toContain("parseSnapshotPortfolioHistory")
    expect(historyContract).toContain('components["schemas"]["PortfolioHistoryResponse"]')
    expect(historyContract).toContain("MAX_POINTS = 512")
    expect(route).toContain("readSnapshotBackedPortfolioHistory")
    expect(transport).toContain('client.GET("/api/v1/portfolio/history"')
    expect(transport).toContain("createAuthenticatedPythonTransport")
    expect(page).not.toContain("activeHistoryPoint")
    expect(page).not.toContain("displayPoint")
    expect(page).not.toContain("latestHistoryPoint")
    expect(page).toContain("Historie celého portfolia")
    expect(page).toContain("historyState.data.currency")
    expect(page).not.toMatch(/historyState.*(?:summary|positions|allocation)/i)
    expect(`${route}\n${transport}\n${historyClient}`).not.toMatch(
      /getPortfolioSnapshotHistory|@\/modules\/snapshots|@\/modules\/portfolio\/rates|@\/lib\/prisma|assertAccountAccess|historical price|historical FX|\/api\/rates/
    )
  })

  it("isolates the only Decimal-to-number conversion in the leaf allocation chart", async () => {
    const page = await source("src/app/portfolio/page.tsx")
    const model = await source("src/modules/portfolio/snapshot-page-model.ts")
    const holdings = await source("src/modules/portfolio/SnapshotHoldingsTable.tsx")
    const breakdown = await source("src/modules/portfolio/SnapshotCurrencyBreakdown.tsx")
    const allocation = await source("src/modules/portfolio/SnapshotAllocationPie.tsx")

    for (const content of [page, model, holdings, breakdown]) {
      expect(content).not.toMatch(/\b(?:Number|parseFloat|parseInt)\s*\(/)
      expect(content).not.toMatch(/\bMath\./)
      expect(content).not.toContain(".toFixed(")
      expect(content).not.toContain(".reduce(")
      expect(content).not.toContain(".sort(")
    }
    expect(allocation.match(/\bNumber\s*\(/g)).toHaveLength(1)
    expect(allocation).toContain("Presentation-only conversion at the Recharts leaf boundary")
    expect(allocation).not.toMatch(/\b(?:Math|parseFloat|parseInt)\b/)
    expect(allocation).not.toContain(".toFixed(")
  })

  it("keeps unrelated routes byte-identical and pins the approved OpenAPI", async () => {
    await expect(sha256("src/app/api/portfolio/route.ts")).resolves.toBe(
      "a769510a35313674d485505fe3b1178c323b96675a7bad1c87644f164c7653f8"
    )
    await expect(sha256("src/app/api/snapshot-workflow/portfolio/route.ts")).resolves.toBe(
      "add630f02a576ea7cfb826810b050f15a0480614fe9990b5a7b9367f2c06365c"
    )
    await expect(sha256("src/app/api/snapshot-workflow/dashboard/route.ts")).resolves.toBe(
      "e6a30f2ddb6235dff68fded44950632d9575bf61b08a282b3b0b99c80962763d"
    )
    await expect(sha256("src/generated/python-api.ts")).resolves.toBe(
      "02f13a292cd5599a207434e4f4341943f570f508417b6594dfb6c8094b777a88"
    )
  })
})
