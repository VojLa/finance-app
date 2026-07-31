import "server-only"

import { describe, expect, it, vi } from "vitest"

import type {
  DashboardSnapshotData,
  PortfolioSnapshotData,
  PythonSnapshotRefreshResponse,
} from "../snapshot-workflow-contract"
import type { PythonSnapshotApi } from "./client"
import { runDashboardSnapshotWorkflow, runPortfolioSnapshotWorkflow } from "./snapshot-workflow"

const IDENTITY = { userId: "user-1", email: "user@example.test" }

const VALID_REFRESH: PythonSnapshotRefreshResponse = {
  netWorthSnapshotId: "net-worth-1",
  netWorthStatus: "created",
  timestamp: "2036-01-02T03:04:00.000",
  granularity: "minute",
  currency: "EUR",
  calculationVersion: 7,
  accounts: [
    { accountId: "account-b", snapshotId: "snapshot-b" },
    { accountId: "account-a", snapshotId: "snapshot-a" },
  ],
  refreshAccountCount: 1,
  reuseOnlyAccountCount: 1,
  createdAccountSnapshotCount: 1,
  replayedAccountSnapshotCount: 0,
  reusedAccountSnapshotCount: 1,
  selectedAccountSnapshotCount: 2,
}

const EMPTY_REFRESH: PythonSnapshotRefreshResponse = {
  ...VALID_REFRESH,
  accounts: [],
  refreshAccountCount: 0,
  reuseOnlyAccountCount: 0,
  createdAccountSnapshotCount: 0,
  replayedAccountSnapshotCount: 0,
  reusedAccountSnapshotCount: 0,
  selectedAccountSnapshotCount: 0,
}

const PORTFOLIO_RESPONSE = {
  timestamp: VALID_REFRESH.timestamp,
  granularity: VALID_REFRESH.granularity,
  currency: VALID_REFRESH.currency,
  calculationVersion: VALID_REFRESH.calculationVersion,
  summary: {
    totalValue: "123456789.123456",
    investmentValue: "100.000001",
  },
  accounts: [
    {
      snapshotId: "snapshot-b",
      account: { accountId: "account-b" },
      summary: { totalValue: "20.000001" },
    },
    {
      snapshotId: "snapshot-a",
      account: { accountId: "account-a" },
      summary: { totalValue: "10.000001" },
    },
  ],
} as unknown as PortfolioSnapshotData

const DASHBOARD_RESPONSE = {
  timestamp: VALID_REFRESH.timestamp,
  granularity: VALID_REFRESH.granularity,
  currency: VALID_REFRESH.currency,
  calculationVersion: VALID_REFRESH.calculationVersion,
  summary: {
    totalValue: "123456789.123456",
    investmentValue: "100.000001",
  },
  accounts: [
    { accountId: "account-a", snapshotId: "snapshot-a", totalValue: "10.000001" },
    { accountId: "account-b", snapshotId: "snapshot-b", totalValue: "20.000001" },
  ],
  assetTypeAllocations: [{ value: "100.000001", allocationPct: "100.000000" }],
  topPositions: [{ accountId: "account-b", value: "100.000001" }],
} as unknown as DashboardSnapshotData

type ApiMocks = {
  api: PythonSnapshotApi
  refresh: ReturnType<typeof vi.fn>
  portfolio: ReturnType<typeof vi.fn>
  dashboard: ReturnType<typeof vi.fn>
}

function apiMocks(
  options: {
    refresh?: unknown
    portfolio?: unknown
    dashboard?: unknown
  } = {}
): ApiMocks {
  const refresh = vi.fn(async () => ("refresh" in options ? options.refresh : VALID_REFRESH))
  const portfolio = vi.fn(async () =>
    "portfolio" in options ? options.portfolio : PORTFOLIO_RESPONSE
  )
  const dashboard = vi.fn(async () =>
    "dashboard" in options ? options.dashboard : DASHBOARD_RESPONSE
  )
  return {
    api: {
      recalculateSnapshotRefresh: refresh,
      readPortfolioSnapshot: portfolio,
      readDashboardSnapshot: dashboard,
    } as PythonSnapshotApi,
    refresh,
    portfolio,
    dashboard,
  }
}

function expectContractError(result: Promise<unknown>) {
  return expect(result).rejects.toMatchObject({
    status: 502,
    code: "python_api_contract_error",
    message: "The Python API returned an incompatible response.",
  })
}

describe("portfolio snapshot workflow", () => {
  it("calls refresh first, forwards the exact ordered manifest, and calls portfolio once", async () => {
    const mocks = apiMocks()

    const result = await runPortfolioSnapshotWorkflow(IDENTITY, mocks.api)

    expect(mocks.refresh).toHaveBeenCalledTimes(1)
    expect(mocks.portfolio).toHaveBeenCalledTimes(1)
    expect(mocks.dashboard).not.toHaveBeenCalled()
    expect(mocks.refresh.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.portfolio.mock.invocationCallOrder[0]
    )
    expect(mocks.portfolio).toHaveBeenCalledWith({
      timestamp: VALID_REFRESH.timestamp,
      granularity: VALID_REFRESH.granularity,
      currency: VALID_REFRESH.currency,
      calculationVersion: VALID_REFRESH.calculationVersion,
      accounts: VALID_REFRESH.accounts,
    })
    const manifest = mocks.portfolio.mock.calls[0][0]
    expect(manifest.accounts).toBe(VALID_REFRESH.accounts)
    expect(manifest.accounts.map((item: { accountId: string }) => item.accountId)).toEqual([
      "account-b",
      "account-a",
    ])
    expect(result).toEqual({
      status: "ready",
      refresh: {
        netWorthSnapshotId: "net-worth-1",
        netWorthStatus: "created",
        timestamp: VALID_REFRESH.timestamp,
        granularity: "minute",
        currency: "EUR",
        calculationVersion: 7,
        refreshAccountCount: 1,
        reuseOnlyAccountCount: 1,
        createdAccountSnapshotCount: 1,
        replayedAccountSnapshotCount: 0,
        reusedAccountSnapshotCount: 1,
        selectedAccountSnapshotCount: 2,
      },
      data: PORTFOLIO_RESPONSE,
    })
  })

  it("preserves all portfolio Decimal strings and response identity", async () => {
    const mocks = apiMocks()
    const result = await runPortfolioSnapshotWorkflow(IDENTITY, mocks.api)

    expect(result.status).toBe("ready")
    if (result.status === "ready") {
      expect(result.data).toBe(PORTFOLIO_RESPONSE)
      expect(result.data.summary.totalValue).toBe("123456789.123456")
      expect(result.data.accounts[0].summary.totalValue).toBe("20.000001")
    }
  })

  it.each(["timestamp", "granularity", "currency", "calculationVersion"] as const)(
    "fails closed on portfolio %s mismatch",
    async (field) => {
      const mocks = apiMocks({
        portfolio: { ...PORTFOLIO_RESPONSE, [field]: "incompatible" },
      })
      await expectContractError(runPortfolioSnapshotWorkflow(IDENTITY, mocks.api))
    }
  )

  it("fails closed on a portfolio account mismatch", async () => {
    const mocks = apiMocks({
      portfolio: {
        ...PORTFOLIO_RESPONSE,
        accounts: [
          { snapshotId: "snapshot-b", account: { accountId: "wrong-account" } },
          PORTFOLIO_RESPONSE.accounts[1],
        ],
      },
    })
    await expectContractError(runPortfolioSnapshotWorkflow(IDENTITY, mocks.api))
  })

  it("fails closed on a portfolio snapshot mismatch", async () => {
    const mocks = apiMocks({
      portfolio: {
        ...PORTFOLIO_RESPONSE,
        accounts: [
          { snapshotId: "wrong-snapshot", account: { accountId: "account-b" } },
          PORTFOLIO_RESPONSE.accounts[1],
        ],
      },
    })
    await expectContractError(runPortfolioSnapshotWorkflow(IDENTITY, mocks.api))
  })
})

describe("dashboard snapshot workflow", () => {
  it("calls refresh first, calls dashboard once, and accepts presentation ordering", async () => {
    const mocks = apiMocks()

    const result = await runDashboardSnapshotWorkflow(IDENTITY, mocks.api)

    expect(mocks.refresh).toHaveBeenCalledTimes(1)
    expect(mocks.dashboard).toHaveBeenCalledTimes(1)
    expect(mocks.portfolio).not.toHaveBeenCalled()
    expect(mocks.refresh.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.dashboard.mock.invocationCallOrder[0]
    )
    expect(mocks.dashboard).toHaveBeenCalledWith({
      timestamp: VALID_REFRESH.timestamp,
      granularity: VALID_REFRESH.granularity,
      currency: VALID_REFRESH.currency,
      calculationVersion: VALID_REFRESH.calculationVersion,
      accounts: VALID_REFRESH.accounts,
    })
    expect(result.status).toBe("ready")
    if (result.status === "ready") {
      expect(result.data).toBe(DASHBOARD_RESPONSE)
      expect(result.data.accounts.map((account) => account.accountId)).toEqual([
        "account-a",
        "account-b",
      ])
      expect(result.data.summary.totalValue).toBe("123456789.123456")
    }
  })

  it.each(["timestamp", "granularity", "currency", "calculationVersion"] as const)(
    "fails closed on dashboard %s mismatch",
    async (field) => {
      const mocks = apiMocks({
        dashboard: { ...DASHBOARD_RESPONSE, [field]: "incompatible" },
      })
      await expectContractError(runDashboardSnapshotWorkflow(IDENTITY, mocks.api))
    }
  )

  it("fails closed when dashboard account set differs", async () => {
    const mocks = apiMocks({
      dashboard: {
        ...DASHBOARD_RESPONSE,
        accounts: [
          DASHBOARD_RESPONSE.accounts[0],
          { ...DASHBOARD_RESPONSE.accounts[1], accountId: "wrong-account" },
        ],
      },
    })
    await expectContractError(runDashboardSnapshotWorkflow(IDENTITY, mocks.api))
  })

  it("fails closed when dashboard repeats an account", async () => {
    const mocks = apiMocks({
      dashboard: {
        ...DASHBOARD_RESPONSE,
        accounts: [DASHBOARD_RESPONSE.accounts[0], DASHBOARD_RESPONSE.accounts[0]],
      },
    })
    await expectContractError(runDashboardSnapshotWorkflow(IDENTITY, mocks.api))
  })
})

describe("empty snapshot workflow", () => {
  it.each(["portfolio", "dashboard"] as const)(
    "returns discriminated empty for %s without a 5L request",
    async (kind) => {
      const mocks = apiMocks({ refresh: EMPTY_REFRESH })
      const result =
        kind === "portfolio"
          ? await runPortfolioSnapshotWorkflow(IDENTITY, mocks.api)
          : await runDashboardSnapshotWorkflow(IDENTITY, mocks.api)

      expect(result.status).toBe("empty")
      expect(result).toEqual({
        status: "empty",
        refresh: {
          netWorthSnapshotId: "net-worth-1",
          netWorthStatus: "created",
          timestamp: VALID_REFRESH.timestamp,
          granularity: "minute",
          currency: "EUR",
          calculationVersion: 7,
          refreshAccountCount: 0,
          reuseOnlyAccountCount: 0,
          createdAccountSnapshotCount: 0,
          replayedAccountSnapshotCount: 0,
          reusedAccountSnapshotCount: 0,
          selectedAccountSnapshotCount: 0,
        },
      })
      expect(result).not.toHaveProperty("data")
      expect(result.refresh).not.toHaveProperty("accounts")
      expect(mocks.portfolio).not.toHaveBeenCalled()
      expect(mocks.dashboard).not.toHaveBeenCalled()
    }
  )

  it("rejects any nonzero count in the empty branch", async () => {
    const mocks = apiMocks({
      refresh: {
        ...EMPTY_REFRESH,
        refreshAccountCount: 1,
        createdAccountSnapshotCount: 1,
        selectedAccountSnapshotCount: 1,
      },
    })
    await expectContractError(runPortfolioSnapshotWorkflow(IDENTITY, mocks.api))
    expect(mocks.portfolio).not.toHaveBeenCalled()
  })
})

describe("refresh corruption", () => {
  it.each([
    ["malformed body", null],
    ["accounts is not an array", { ...VALID_REFRESH, accounts: {} }],
    [
      "account item is not an object",
      { ...VALID_REFRESH, accounts: ["invalid", VALID_REFRESH.accounts[1]] },
    ],
    [
      "duplicate account ID",
      {
        ...VALID_REFRESH,
        accounts: [VALID_REFRESH.accounts[0], { accountId: "account-b", snapshotId: "snapshot-a" }],
      },
    ],
    [
      "duplicate snapshot ID",
      {
        ...VALID_REFRESH,
        accounts: [VALID_REFRESH.accounts[0], { accountId: "account-a", snapshotId: "snapshot-b" }],
      },
    ],
    [
      "blank account ID",
      {
        ...VALID_REFRESH,
        accounts: [{ accountId: " ", snapshotId: "snapshot-b" }, VALID_REFRESH.accounts[1]],
      },
    ],
    [
      "untrimmed account ID",
      {
        ...VALID_REFRESH,
        accounts: [
          { accountId: " account-b", snapshotId: "snapshot-b" },
          VALID_REFRESH.accounts[1],
        ],
      },
    ],
    [
      "blank snapshot ID",
      {
        ...VALID_REFRESH,
        accounts: [{ accountId: "account-b", snapshotId: "" }, VALID_REFRESH.accounts[1]],
      },
    ],
    ["count mismatch", { ...VALID_REFRESH, selectedAccountSnapshotCount: 1 }],
    ["negative count", { ...VALID_REFRESH, createdAccountSnapshotCount: -1 }],
    ["refresh disposition mismatch", { ...VALID_REFRESH, replayedAccountSnapshotCount: 1 }],
    ["reuse disposition mismatch", { ...VALID_REFRESH, reusedAccountSnapshotCount: 0 }],
    ["invalid currency", { ...VALID_REFRESH, currency: "eur" }],
    ["invalid calculation version", { ...VALID_REFRESH, calculationVersion: 0 }],
    ["fractional calculation version", { ...VALID_REFRESH, calculationVersion: 1.5 }],
    ["blank timestamp", { ...VALID_REFRESH, timestamp: "" }],
    ["blank granularity", { ...VALID_REFRESH, granularity: "" }],
  ])("maps %s to the generic response contract error", async (_label, refresh) => {
    const mocks = apiMocks({ refresh })

    await expectContractError(runPortfolioSnapshotWorkflow(IDENTITY, mocks.api))
    expect(mocks.portfolio).not.toHaveBeenCalled()
    expect(mocks.dashboard).not.toHaveBeenCalled()
  })
})
