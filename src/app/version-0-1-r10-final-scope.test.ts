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

    expect(workflow).toContain("api.readCurrentPortfolio()")
    expect(workflow).toContain("api.readCurrentDashboard()")
    expect(client).toContain('"/api/v1/portfolio/current"')
    expect(client).toContain('"/api/v1/dashboard/current"')

    const activeWorkflows = workflow.slice(
      workflow.indexOf("export async function runPortfolioSnapshotWorkflow")
    )
    expect(activeWorkflows).not.toContain("recalculateSnapshotRefresh")
    expect(activeWorkflows).not.toContain("snapshot-refresh/recalculate")
  })
})
