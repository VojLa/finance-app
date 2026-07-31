import { createHash } from "node:crypto"
import { execFileSync } from "node:child_process"
import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()
const BASE_SHA = "e34fc2d17915a6159fa2856520c503bf8b6f70b8"

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

async function sha256(relativePath: string): Promise<string> {
  return createHash("sha256")
    .update(await readFile(path.join(ROOT, relativePath)))
    .digest("hex")
}

function changedFiles(): string[] {
  const tracked = execFileSync("git", ["diff", "--name-only", BASE_SHA, "--"], {
    cwd: ROOT,
    encoding: "utf8",
  })
  const untracked = execFileSync("git", ["ls-files", "--others", "--exclude-standard"], {
    cwd: ROOT,
    encoding: "utf8",
  })
  return `${tracked}\n${untracked}`
    .split(/\r?\n/)
    .filter(Boolean)
    .map((file) => file.replaceAll("\\", "/"))
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

  it("keeps forbidden implementation targets byte-identical", async () => {
    await expect(sha256("src/app/portfolio/page.tsx")).resolves.toBe(
      "12b81e3b83b6d9c55004685f34461c935fbf93d3b23ca3ddb9e3744cba1b58a8"
    )
    await expect(sha256("src/app/api/dashboard/route.ts")).resolves.toBe(
      "018dfe28e81da5b780df309805ae81ff7c83fb35b9ce8b1ba8e33dda264ce9ee"
    )
    await expect(sha256("src/app/api/snapshot-workflow/portfolio/route.ts")).resolves.toBe(
      "add630f02a576ea7cfb826810b050f15a0480614fe9990b5a7b9367f2c06365c"
    )
    await expect(sha256("src/app/api/snapshot-workflow/dashboard/route.ts")).resolves.toBe(
      "e6a30f2ddb6235dff68fded44950632d9575bf61b08a282b3b0b99c80962763d"
    )
    await expect(sha256("src/generated/python-api.ts")).resolves.toBe(
      "2b688f92f2f2f39ecf2642631a52a383d9d6293df5c8c0ef9fe75846c1b55f08"
    )
  })

  it("changes no Python, Prisma, migration, portfolio, workflow-route, or generated implementation", () => {
    const changed = changedFiles()
    const forbiddenPrefixes = [
      "backend/python/",
      "prisma/",
      "src/app/portfolio/page.tsx",
      "src/modules/portfolio/",
      "src/app/api/dashboard/route.ts",
      "src/app/api/snapshot-workflow/portfolio/route.ts",
      "src/app/api/snapshot-workflow/dashboard/route.ts",
      "src/generated/python-api.ts",
    ]

    for (const file of changed) {
      expect(
        forbiddenPrefixes.some((prefix) => file === prefix || file.startsWith(prefix)),
        file
      ).toBe(false)
    }
  })
})
