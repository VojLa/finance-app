import "server-only"

import { describe, expect, it, vi } from "vitest"

import {
  anycoinIncompleteDashboardSnapshotFixture,
  dashboardSnapshotFixture,
} from "@/test/dashboard-snapshot-fixture"
import {
  anycoinIncompletePortfolioSnapshotFixture,
  portfolioSnapshotFixture,
} from "@/test/portfolio-snapshot-fixture"
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

  it.each([
    ["missing cost breakdown", undefined],
    ["empty cost breakdown", []],
    [
      "duplicate cost currency",
      [
        { currency: "EUR", amount: "1.0000000000" },
        { currency: "EUR", amount: "2.0000000000" },
      ],
    ],
    [
      "unsorted cost currencies",
      [
        { currency: "USD", amount: "1.0000000000" },
        { currency: "EUR", amount: "2.0000000000" },
      ],
    ],
    ["zero cost component", [{ currency: "EUR", amount: "0.0000000000" }]],
  ])("fails closed on %s", async (_label, nativeCostBasisByCurrency) => {
    const payload = portfolioSnapshotFixture()
    payload.accounts[0].positions[0] = {
      ...payload.accounts[0].positions[0],
      nativeCostBasisByCurrency,
    } as never
    await contractFailure(runPortfolioSnapshotWorkflow(IDENTITY, api(payload)))
  })

  it("accepts one correlated incomplete Anycoin branch without changing quantity or value", async () => {
    const payload = anycoinIncompletePortfolioSnapshotFixture()
    const result = await runPortfolioSnapshotWorkflow(IDENTITY, api(payload))
    const anycoin = result.data.accounts[1]?.positions[0]

    expect(result.data.summary.investmentCostBasis).toBeNull()
    expect(result.data.summary.netDepositsValue).toBeNull()
    expect(result.data.summary.realizedPnlValue).toBeNull()
    expect(result.data.summary.unrealizedPnlValue).toBeNull()
    expect(anycoin).toMatchObject({
      quantity: "1.0000000000",
      value: "40.000000",
      costBasis: null,
      unrealizedPnl: null,
      nativeCostBasis: null,
    })
    expect(result.data.accounts[0]?.positions[0]?.costBasis).toBe("100.0000010000")
  })

  it.each([
    ["summary cost only", { investmentCostBasis: "0.000000" }],
    ["summary deposits only", { netDepositsValue: "0.000000" }],
  ])("rejects a partial-null Anycoin %s branch", async (_label, summaryMutation) => {
    const payload = anycoinIncompletePortfolioSnapshotFixture()
    payload.summary = { ...payload.summary, ...summaryMutation } as never
    await contractFailure(runPortfolioSnapshotWorkflow(IDENTITY, api(payload)))
  })

  it("rejects a partial-null position instead of substituting zero", async () => {
    const payload = anycoinIncompletePortfolioSnapshotFixture()
    const position = payload.accounts[1]?.positions[0]
    if (position === undefined) throw new Error("Missing Anycoin fixture position.")
    ;(position as { costBasis: string | null }).costBasis = "0.0000000000"
    await contractFailure(runPortfolioSnapshotWorkflow(IDENTITY, api(payload)))
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

  it("preserves a correlated incomplete Anycoin dashboard branch", async () => {
    const payload = anycoinIncompleteDashboardSnapshotFixture()
    const result = await runDashboardSnapshotWorkflow(IDENTITY, api(undefined, payload))

    expect(result.data.summary.investmentCostBasis).toBeNull()
    expect(result.data.summary.netDepositsValue).toBeNull()
    expect(result.data.summary.realizedPnlValue).toBeNull()
    expect(result.data.summary.unrealizedPnlValue).toBeNull()
    expect(result.data.topPositions.find(({ symbol }) => symbol === "BTC")).toMatchObject({
      value: "2.000001",
      unrealizedPnl: null,
    })
  })

  it("rejects partial-null dashboard summary and account branches", async () => {
    const summaryPayload = anycoinIncompleteDashboardSnapshotFixture()
    ;(summaryPayload.summary as { investmentCostBasis: string | null }).investmentCostBasis =
      "0.000000"
    await contractFailure(runDashboardSnapshotWorkflow(IDENTITY, api(undefined, summaryPayload)))

    const accountPayload = anycoinIncompleteDashboardSnapshotFixture()
    const account = accountPayload.accounts[0]
    if (account === undefined) throw new Error("Missing Anycoin fixture account.")
    ;(account as { netDepositsValue: string | null }).netDepositsValue = "0.000000"
    await contractFailure(runDashboardSnapshotWorkflow(IDENTITY, api(undefined, accountPayload)))
  })
})
