import { readdir, readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()

async function filesBelow(relativeDirectory: string): Promise<string[]> {
  const entries = await readdir(path.join(ROOT, relativeDirectory), { withFileTypes: true })
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const child = path.join(relativeDirectory, entry.name).replaceAll("\\", "/")
      return entry.isDirectory() ? filesBelow(child) : [child]
    })
  )
  return nested.flat()
}

async function source(relativePath: string) {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

describe("R11-H portfolio and snapshot compatibility removal", () => {
  it("keeps only active portfolio/history/manual and explicit snapshot workflow routes", async () => {
    const apiFiles = await filesBelow("src/app/api")
    const portfolioRoutes = apiFiles
      .filter((file) => /^src\/app\/api\/portfolio(?:\/.*)?\/route\.ts$/.test(file))
      .sort()
    expect(portfolioRoutes).toEqual([
      "src/app/api/portfolio/history/route.ts",
      "src/app/api/portfolio/transactions/route.ts",
    ])

    const workflowRoutes = apiFiles
      .filter((file) => /^src\/app\/api\/snapshot-workflow\/.*\/route\.ts$/.test(file))
      .sort()
    expect(workflowRoutes).toEqual([
      "src/app/api/snapshot-workflow/dashboard/route.ts",
      "src/app/api/snapshot-workflow/portfolio/refresh/route.ts",
      "src/app/api/snapshot-workflow/portfolio/route.ts",
    ])
    expect(apiFiles).not.toContain("src/app/api/rates/route.ts")
  })

  it("contains no TypeScript finance engine or compatibility barrel", async () => {
    const productionFiles = (await filesBelow("src")).filter(
      (file) => !file.endsWith(".test.ts") && !file.endsWith(".test.tsx")
    )
    const forbiddenPaths = productionFiles.filter((file) =>
      /src\/(?:modules\/(?:snapshots|holdings|fx|pricing)|modules\/portfolio\/(?:rates|positions|ledger)|lib\/portfolio\.ts)/.test(
        file
      )
    )
    expect(forbiddenPaths).toEqual([])

    const activeFinanceBoundary = await Promise.all(
      [
        "src/app/api/snapshot-workflow/dashboard/route.ts",
        "src/app/api/snapshot-workflow/portfolio/refresh/route.ts",
        "src/app/api/snapshot-workflow/portfolio/route.ts",
        "src/app/api/portfolio/history/route.ts",
        "src/modules/python-api/server/snapshot-workflow.ts",
        "src/modules/python-api/server/portfolio-history.ts",
      ].map(source)
    )
    expect(activeFinanceBoundary.join("\n")).not.toMatch(
      /@\/lib\/prisma|\bprisma\.|Yahoo|yahoo|createPortfolioSnapshot|recalculateHoldings|getLivePrices|getCzkRates/
    )
  })
})
