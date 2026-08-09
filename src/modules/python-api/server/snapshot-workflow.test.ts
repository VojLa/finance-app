import "server-only"

import { describe, expect, it, vi } from "vitest"

import { dashboardSnapshotFixture } from "@/test/dashboard-snapshot-fixture"
import { portfolioSnapshotFixture } from "@/test/portfolio-snapshot-fixture"
import type { PythonSnapshotApi } from "./client"
import { runDashboardSnapshotWorkflow, runPortfolioSnapshotWorkflow } from "./snapshot-workflow"

const IDENTITY = { userId: "user-1", email: "user@example.test" }

function api(
  portfolio: unknown = portfolioSnapshotFixture(),
  dashboard: unknown = dashboardSnapshotFixture
): PythonSnapshotApi {
  return {
    recalculateSnapshotRefresh: vi.fn(),
    readPortfolioSnapshot: vi.fn(),
    readDashboardSnapshot: vi.fn(),
    readCurrentPortfolio: vi.fn(async () => portfolio as never),
    readCurrentDashboard: vi.fn(async () => dashboard as never),
  }
}

async function contractFailure(result: Promise<unknown>) {
  await expect(result).rejects.toMatchObject({
    code: "python_api_contract_error",
    status: 502,
  })
}

describe("strict current portfolio workflow", () => {
  it("preserves exact current response and explicit lineage summary", async () => {
    const client = api()
    const result = await runPortfolioSnapshotWorkflow(IDENTITY, client)

    expect(result.data).toBe(await client.readCurrentPortfolio())
    expect(result.current).toEqual({
      asOf: portfolioSnapshotFixture().asOf,
      baselineTimestamp: portfolioSnapshotFixture().baselineTimestamp,
      historyAnchorSnapshotId: "net-worth-baseline",
      currency: "EUR",
      calculationVersion: 7,
    })
    expect(client.recalculateSnapshotRefresh).not.toHaveBeenCalled()
  })

  it.each([
    ["missing asOf", { asOf: undefined }],
    ["bad currency", { currency: "eur" }],
    ["bad money", { summary: { ...portfolioSnapshotFixture().summary, totalValue: "1.0" } }],
  ])("fails closed on %s", async (_label, mutation) => {
    await contractFailure(
      runPortfolioSnapshotWorkflow(IDENTITY, api({ ...portfolioSnapshotFixture(), ...mutation }))
    )
  })
})

describe("strict current dashboard workflow", () => {
  it("uses one direct current endpoint and preserves account presentation money", async () => {
    const client = api()
    const result = await runDashboardSnapshotWorkflow(IDENTITY, client)

    expect(result.data.accounts[0].netDepositsValue).toBe("1250.000000")
    expect(client.readCurrentDashboard).toHaveBeenCalledOnce()
    expect(client.recalculateSnapshotRefresh).not.toHaveBeenCalled()
  })

  it.each([
    ["missing baseline", { baselineTimestamp: undefined }],
    ["number money", { accounts: [{ ...dashboardSnapshotFixture.accounts[0], totalValue: 1 }] }],
    [
      "relabeled currency",
      {
        accounts: [
          { ...dashboardSnapshotFixture.accounts[0], outputCurrency: "EUR" },
          dashboardSnapshotFixture.accounts[1],
        ],
      },
    ],
  ])("fails closed on %s", async (_label, mutation) => {
    await contractFailure(
      runDashboardSnapshotWorkflow(
        IDENTITY,
        api(undefined, { ...dashboardSnapshotFixture, ...mutation })
      )
    )
  })
})
