import { readFileSync } from "node:fs"
import { join } from "node:path"

import { describe, expect, it } from "vitest"

const root = process.cwd()

function source(path: string): string {
  return readFileSync(join(root, path), "utf8")
}

describe("Version 0.1 R10 final active current-value browser boundary", () => {
  it("keeps portfolio and dashboard as authenticated thin adapters", () => {
    for (const path of [
      "src/app/api/snapshot-workflow/portfolio/route.ts",
      "src/app/api/snapshot-workflow/dashboard/route.ts",
    ]) {
      const text = source(path)
      expect(text).toContain("getServerSession(authOptions)")
      expect(text).toContain("session.user.id")
      expect(text).not.toContain("Prisma")
      expect(text).not.toContain("/api/rates")
      expect(text).not.toContain("snapshot-refresh/recalculate")
    }
  })

  it("uses the Python current endpoints without the old minute-refresh workflow", () => {
    const workflow = source("src/modules/python-api/server/snapshot-workflow.ts")
    const client = source("src/modules/python-api/server/client.ts")

    expect(workflow).toContain("api.readPublishedPortfolio()")
    expect(workflow).toContain("api.readPublishedDashboard()")
    expect(client).toContain('"/api/v1/portfolio/published"')
    expect(client).toContain('"/api/v1/dashboard/published"')

    const activeWorkflows = workflow.slice(
      workflow.indexOf("export async function runPortfolioSnapshotWorkflow"),
      workflow.indexOf("export async function refreshPortfolioSnapshotWorkflow")
    )
    expect(activeWorkflows).not.toContain("recalculateSnapshotRefresh")
    expect(activeWorkflows).not.toContain("snapshot-refresh/recalculate")

    const refreshRoute = source("src/app/api/snapshot-workflow/portfolio/refresh/route.ts")
    expect(refreshRoute).toContain("export async function POST")
    expect(refreshRoute).toContain("refreshPortfolioSnapshotWorkflow")
    expect(refreshRoute).not.toMatch(/export\s+(?:async\s+)?function\s+GET/)
    expect(workflow).toContain("await api.recalculateSnapshotRefresh()")
  })
})
