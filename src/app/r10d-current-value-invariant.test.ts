import "server-only"

import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it, vi } from "vitest"

import type { PythonSnapshotApi } from "@/modules/python-api/server/client"
import {
  runDashboardSnapshotWorkflow,
  runPortfolioSnapshotWorkflow,
} from "@/modules/python-api/server/snapshot-workflow"
import { dashboardSnapshotFixture } from "@/test/dashboard-snapshot-fixture"
import { portfolioSnapshotFixture } from "@/test/portfolio-snapshot-fixture"

const IDENTITY = { userId: "r10d2-user", email: "r10d2@example.test" }

function portfolioCurrentFixture() {
  const value = portfolioSnapshotFixture()
  return { ...value, valuationTimestamp: value.asOf, isStale: false }
}

const dashboardCurrentFixture = {
  ...dashboardSnapshotFixture,
  valuationTimestamp: dashboardSnapshotFixture.asOf,
  isStale: false,
}

function api(): PythonSnapshotApi {
  return {
    recalculateSnapshotRefresh: vi.fn(),
    readPortfolioSnapshot: vi.fn(),
    readDashboardSnapshot: vi.fn(),
    readCurrentPortfolio: vi.fn(async () => portfolioCurrentFixture()),
    readCurrentDashboard: vi.fn(async () => dashboardCurrentFixture),
    readPublishedPortfolio: vi.fn(async () => portfolioCurrentFixture()),
    readPublishedDashboard: vi.fn(async () => dashboardCurrentFixture),
  }
}

async function source(file: string): Promise<string> {
  return readFile(path.join(process.cwd(), file), "utf8")
}

describe("R10-D2 active current-value workflow", () => {
  it("reads ephemeral portfolio directly without snapshot refresh", async () => {
    const client = api()
    const result = await runPortfolioSnapshotWorkflow(IDENTITY, client)

    expect(result.status).toBe("ready")
    expect(result.current.asOf).toBe(portfolioSnapshotFixture().asOf)
    expect(client.readPublishedPortfolio).toHaveBeenCalledOnce()
    expect(client.recalculateSnapshotRefresh).not.toHaveBeenCalled()
    expect(client.readPortfolioSnapshot).not.toHaveBeenCalled()
  })

  it("reads dashboard from the same Python current-value boundary", async () => {
    const client = api()
    const result = await runDashboardSnapshotWorkflow(IDENTITY, client)

    expect(result.current.asOf).toBe(dashboardSnapshotFixture.asOf)
    expect(client.readPublishedDashboard).toHaveBeenCalledOnce()
    expect(client.recalculateSnapshotRefresh).not.toHaveBeenCalled()
    expect(client.readDashboardSnapshot).not.toHaveBeenCalled()
  })

  it("keeps browser adapters thin and removes the active minute-refresh path", async () => {
    const files = [
      "src/app/api/snapshot-workflow/portfolio/route.ts",
      "src/app/api/snapshot-workflow/dashboard/route.ts",
      "src/modules/python-api/server/snapshot-workflow.ts",
      "src/modules/python-api/server/client.ts",
    ]
    const content = (await Promise.all(files.map(source))).join("\n")

    expect(content).toContain("/api/v1/portfolio/published")
    expect(content).toContain("/api/v1/dashboard/published")
    expect(content).not.toMatch(/Prisma|\/api\/rates/)
    const workflow = await source("src/modules/python-api/server/snapshot-workflow.ts")
    const readWorkflow = workflow.slice(
      workflow.indexOf("export async function runPortfolioSnapshotWorkflow"),
      workflow.indexOf("export async function refreshPortfolioSnapshotWorkflow")
    )
    expect(readWorkflow).not.toContain("recalculateSnapshotRefresh()")
    expect(workflow).toContain("await api.recalculateSnapshotRefresh()")
    expect(workflow).toContain("value.valuationTimestamp")
    expect(workflow).toContain("value.isStale")
    expect(await source("src/app/api/snapshot-workflow/portfolio/refresh/route.ts")).toContain(
      "refreshPortfolioSnapshotWorkflow"
    )
  })

  it("keeps history on persisted Python NetWorthSnapshot evidence", async () => {
    const route = await source("src/app/api/portfolio/history/route.ts")
    const client = await source("src/modules/python-api/server/portfolio-history.ts")

    expect(route).toContain("readGenerationPortfolioHistory")
    expect(client).toContain("/api/v1/portfolio/history")
    expect(client).not.toContain("portfolio/current")
  })
})
