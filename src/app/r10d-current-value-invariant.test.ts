import "server-only"

import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it, vi } from "vitest"

import type {
  DashboardSnapshotData,
  ExactPortfolioSnapshotManifest,
  PortfolioSnapshotData,
  PythonSnapshotRefreshResponse,
} from "@/modules/python-api/snapshot-workflow-contract"
import type { PythonSnapshotApi } from "@/modules/python-api/server/client"
import {
  runDashboardSnapshotWorkflow,
  runPortfolioSnapshotWorkflow,
} from "@/modules/python-api/server/snapshot-workflow"
import { dashboardSnapshotFixture } from "@/test/dashboard-snapshot-fixture"
import { portfolioSnapshotFixture } from "@/test/portfolio-snapshot-fixture"

const IDENTITY = { userId: "r10d-user", email: "r10d@example.test" }
const TIMESTAMP = "2038-05-06T21:43:00.000"

function refreshFor(
  data: PortfolioSnapshotData | DashboardSnapshotData
): PythonSnapshotRefreshResponse {
  const accounts = data.accounts.map((account) => ({
    accountId: "account" in account ? account.account.accountId : account.accountId,
    snapshotId: account.primarySnapshotId,
  }))
  return {
    netWorthSnapshotId: "r10d-net-worth",
    netWorthStatus: "created",
    timestamp: TIMESTAMP,
    granularity: "minute",
    currency: data.currency,
    calculationVersion: data.calculationVersion,
    accounts,
    refreshAccountCount: accounts.length,
    reuseOnlyAccountCount: 0,
    createdAccountSnapshotCount: accounts.length,
    replayedAccountSnapshotCount: 0,
    reusedAccountSnapshotCount: 0,
    selectedAccountSnapshotCount: accounts.length,
  }
}

function currentPortfolio(): PortfolioSnapshotData {
  return {
    ...portfolioSnapshotFixture(),
    timestamp: TIMESTAMP,
    granularity: "minute",
  }
}

function currentDashboard(): DashboardSnapshotData {
  return {
    ...dashboardSnapshotFixture,
    timestamp: TIMESTAMP,
    granularity: "minute",
  }
}

function apiFor<T extends PortfolioSnapshotData | DashboardSnapshotData>(
  data: T,
  calls: string[],
  manifests: ExactPortfolioSnapshotManifest[]
): PythonSnapshotApi {
  const refresh = refreshFor(data)
  return {
    recalculateSnapshotRefresh: vi.fn(async () => {
      calls.push("refresh")
      return refresh
    }),
    readPortfolioSnapshot: vi.fn(async (manifest) => {
      calls.push("portfolio")
      manifests.push(manifest)
      return data as PortfolioSnapshotData
    }),
    readDashboardSnapshot: vi.fn(async (manifest) => {
      calls.push("dashboard")
      manifests.push(manifest)
      return data as DashboardSnapshotData
    }),
  }
}

async function source(file: string): Promise<string> {
  return readFile(path.join(process.cwd(), file), "utf8")
}

describe("R10-D active current-value workflow audit", () => {
  it("refreshes before the portfolio read and forwards only the exact returned manifest", async () => {
    const data = currentPortfolio()
    const calls: string[] = []
    const manifests: ExactPortfolioSnapshotManifest[] = []

    const result = await runPortfolioSnapshotWorkflow(IDENTITY, apiFor(data, calls, manifests))

    expect(result.status).toBe("ready")
    expect(calls).toEqual(["refresh", "portfolio"])
    expect(manifests).toEqual([
      {
        timestamp: TIMESTAMP,
        granularity: "minute",
        currency: data.currency,
        calculationVersion: data.calculationVersion,
        accounts: refreshFor(data).accounts,
      },
    ])
  })

  it("refreshes before the dashboard read and forwards only the exact returned manifest", async () => {
    const data = currentDashboard()
    const calls: string[] = []
    const manifests: ExactPortfolioSnapshotManifest[] = []

    const result = await runDashboardSnapshotWorkflow(IDENTITY, apiFor(data, calls, manifests))

    expect(result.status).toBe("ready")
    expect(calls).toEqual(["refresh", "dashboard"])
    expect(manifests[0]).toEqual({
      timestamp: TIMESTAMP,
      granularity: "minute",
      currency: data.currency,
      calculationVersion: data.calculationVersion,
      accounts: refreshFor(data).accounts,
    })
  })

  it("keeps browser routes thin and contains no daily selector, delta engine, Prisma, or rates fallback", async () => {
    const files = [
      "src/app/api/snapshot-workflow/portfolio/route.ts",
      "src/app/api/snapshot-workflow/dashboard/route.ts",
      "src/modules/python-api/server/snapshot-workflow.ts",
      "src/modules/python-api/server/client.ts",
    ]
    const content = (await Promise.all(files.map(source))).join("\n")

    expect(content).toContain("runPortfolioSnapshotWorkflow")
    expect(content).toContain("runDashboardSnapshotWorkflow")
    expect(content).toContain("/api/v1/snapshot-refresh/recalculate")
    expect(content).not.toMatch(/SnapshotGranularity\.day|daily snapshot|post-baseline/i)
    expect(content).not.toMatch(/\b(?:Prisma|Transaction|InvestmentEvent|Holding)\b/)
    expect(content).not.toContain("/api/rates")
    expect(content).not.toMatch(/latest|nearest/i)
  })

  it("keeps history on its separate persisted Python endpoint", async () => {
    const route = await source("src/app/api/portfolio/history/route.ts")
    const client = await source("src/modules/python-api/server/portfolio-history.ts")

    expect(route).toContain("readSnapshotBackedPortfolioHistory")
    expect(client).toContain("/api/v1/portfolio/history")
    expect(route).not.toContain("runPortfolioSnapshotWorkflow")
    expect(client).not.toContain("snapshot-refresh/recalculate")
  })
})
