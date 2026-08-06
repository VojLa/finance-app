import { createHash } from "node:crypto"
import { execFileSync } from "node:child_process"
import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()
const BASE_SHA = "117ca8b09d09cab1bdc9363cf76661d8eedd2c44"
const CUTOVER_SHA = "e34fc2d17915a6159fa2856520c503bf8b6f70b8"

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

async function sha256(relativePath: string): Promise<string> {
  return createHash("sha256")
    .update(await readFile(path.join(ROOT, relativePath)))
    .digest("hex")
}

function changedFiles(): string[] {
  return execFileSync("git", ["diff", "--name-only", BASE_SHA, CUTOVER_SHA, "--"], {
    cwd: ROOT,
    encoding: "utf8",
  })
    .split(/\r?\n/)
    .filter(Boolean)
    .map((file) => file.replaceAll("\\", "/"))
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

  it("keeps history chart-only and separate from current cards and positions", async () => {
    const page = await source("src/app/portfolio/page.tsx")
    const historyClient = await source("src/modules/portfolio/snapshot-history-client.ts")

    expect(historyClient).toContain("/api/portfolio/history?")
    expect(historyClient).not.toContain("accountId")
    expect(historyClient).toContain("History cutover is intentionally outside 5M-C")
    expect(page).not.toContain("activeHistoryPoint")
    expect(page).not.toContain("displayPoint")
    expect(page).not.toContain("latestHistoryPoint")
    expect(page).not.toMatch(/history.*(?:summary|positions|currency)/i)
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

  it("keeps legacy and workflow routes byte-identical and pins the approved OpenAPI", async () => {
    await expect(sha256("src/app/api/portfolio/route.ts")).resolves.toBe(
      "a769510a35313674d485505fe3b1178c323b96675a7bad1c87644f164c7653f8"
    )
    await expect(sha256("src/app/api/portfolio/history/route.ts")).resolves.toBe(
      "2dfbcf8c5c6429c6eab0f9cb04e993ba14ad32bbacc9dba90c817faad1aba95c"
    )
    await expect(sha256("src/app/api/snapshot-workflow/portfolio/route.ts")).resolves.toBe(
      "add630f02a576ea7cfb826810b050f15a0480614fe9990b5a7b9367f2c06365c"
    )
    await expect(sha256("src/app/api/snapshot-workflow/dashboard/route.ts")).resolves.toBe(
      "e6a30f2ddb6235dff68fded44950632d9575bf61b08a282b3b0b99c80962763d"
    )
    await expect(sha256("src/generated/python-api.ts")).resolves.toBe(
      "8d8b0a692fbc8f2fc2e4418316ff8b549a51b905d606a0109b667e24a9cbc968"
    )
  })

  it("changes no unrelated Python, Prisma, migration, legacy, or workflow-route implementation", () => {
    const changed = changedFiles()
    const approvedPrefixes = ["backend/python/app/modules/portfolio_snapshot/"]
    const forbiddenPrefixes = [
      "backend/python/app/",
      "backend/python/database/",
      "backend/python/migrations/",
      "backend/python/scripts/",
      "backend/python/alembic.ini",
      "backend/python/pyproject.toml",
      "backend/python/uv.lock",
      "prisma/",
      "src/app/api/portfolio/route.ts",
      "src/app/api/portfolio/history/route.ts",
      "src/app/api/snapshot-workflow/portfolio/route.ts",
      "src/app/api/snapshot-workflow/dashboard/route.ts",
    ]

    for (const file of changed) {
      if (approvedPrefixes.some((prefix) => file.startsWith(prefix))) continue
      expect(
        forbiddenPrefixes.some((prefix) => file === prefix || file.startsWith(prefix)),
        file
      ).toBe(false)
    }
  })
})
