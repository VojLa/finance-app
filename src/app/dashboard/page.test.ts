import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it, vi } from "vitest"
import {
  DASHBOARD_WORKFLOW_PATH,
  requestDashboardFinancialState,
} from "@/modules/dashboard/snapshot-dashboard-client"
import {
  OPERATIONAL_DASHBOARD_PATH,
  requestOperationalDashboardState,
} from "@/modules/dashboard/operational-dashboard-client"
import { dashboardSnapshotFixture } from "@/test/dashboard-snapshot-fixture"

const refresh = {
  netWorthSnapshotId: "net-worth-snapshot-1",
  netWorthStatus: "created" as const,
  timestamp: dashboardSnapshotFixture.timestamp,
  granularity: dashboardSnapshotFixture.granularity,
  currency: dashboardSnapshotFixture.currency,
  calculationVersion: dashboardSnapshotFixture.calculationVersion,
  refreshAccountCount: 2,
  reuseOnlyAccountCount: 0,
  createdAccountSnapshotCount: 2,
  replayedAccountSnapshotCount: 0,
  reusedAccountSnapshotCount: 0,
  selectedAccountSnapshotCount: 2,
}

const operationalPayload = {
  summary: {
    cashValueCzk: 1,
    portfolioValueCzk: 2,
    liabilitiesValueCzk: -1,
    netWorthCzk: 2,
    currentMonthIncomeCzk: 100,
    currentMonthExpenseCzk: 40,
    currentMonthNetCzk: 60,
  },
  accountBalances: [{ accountId: "legacy-financial-data" }],
  budget: null,
  expenseByCategory: [],
  monthlyTrends: [],
  recentTransactions: [],
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("dashboard snapshot cutover clients", () => {
  it("uses one bodyless no-store POST and preserves the ready snapshot response", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        status: "ready",
        refresh,
        data: dashboardSnapshotFixture,
      })
    )

    const result = await requestDashboardFinancialState(fetchMock)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith(DASHBOARD_WORKFLOW_PATH, {
      method: "POST",
      cache: "no-store",
    })
    expect(fetchMock.mock.calls[0]?.[0]).not.toContain("?")
    expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("body")
    expect(result).toEqual({
      status: "ready",
      refresh,
      data: dashboardSnapshotFixture,
    })
    if (result.status === "ready") {
      expect(result.data.summary.totalValue).toBe("999999999999.123456")
      expect(result.data.topPositions.map(({ symbol }) => symbol)).toEqual(["ZZZ", "AAA"])
    }
  })

  it("represents empty without data or a legacy financial fallback", async () => {
    const emptyRefresh = {
      ...refresh,
      refreshAccountCount: 0,
      createdAccountSnapshotCount: 0,
      selectedAccountSnapshotCount: 0,
    }
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ status: "empty", refresh: emptyRefresh }))

    const result = await requestDashboardFinancialState(fetchMock)

    expect(result).toEqual({ status: "empty", refresh: emptyRefresh })
    expect(result).not.toHaveProperty("data")
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("returns safe errors, hides raw bodies, and never retries", async () => {
    const backendFailure = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response("secret traceback and token", { status: 502 }))
    const networkFailure = vi.fn<typeof fetch>().mockRejectedValue(new Error("raw network secret"))

    const backendResult = await requestDashboardFinancialState(backendFailure)
    const networkResult = await requestDashboardFinancialState(networkFailure)

    expect(backendResult).toMatchObject({ status: "error", code: "python_api_unavailable" })
    expect(networkResult).toMatchObject({ status: "error", code: "python_api_unavailable" })
    expect(JSON.stringify([backendResult, networkResult])).not.toMatch(
      /traceback|token|raw network secret/
    )
    expect(backendFailure).toHaveBeenCalledTimes(1)
    expect(networkFailure).toHaveBeenCalledTimes(1)
  })

  it("loads the operational subset once with GET and excludes legacy financial fields", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(operationalPayload))

    const result = await requestOperationalDashboardState(fetchMock)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith(OPERATIONAL_DASHBOARD_PATH, {
      method: "GET",
      cache: "no-store",
    })
    expect(result).toEqual({
      status: "ready",
      data: {
        currentMonth: { income: 100, expenses: 40, net: 60 },
        budget: null,
        expenseByCategory: [],
        monthlyTrends: [],
        recentTransactions: [],
      },
    })
    expect(JSON.stringify(result)).not.toMatch(
      /cashValueCzk|portfolioValueCzk|liabilitiesValueCzk|netWorthCzk|accountBalances/
    )
  })

  it("starts the independent initial requests in parallel and refreshes only financial data", async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      if (input === DASHBOARD_WORKFLOW_PATH) {
        return Promise.resolve(
          jsonResponse({ status: "ready", refresh, data: dashboardSnapshotFixture })
        )
      }
      if (input === OPERATIONAL_DASHBOARD_PATH) {
        return Promise.resolve(jsonResponse(operationalPayload))
      }
      return Promise.reject(new Error("unexpected URL"))
    })

    const [financial, operational] = await Promise.all([
      requestDashboardFinancialState(fetchMock),
      requestOperationalDashboardState(fetchMock),
    ])

    expect(financial.status).toBe("ready")
    expect(operational.status).toBe("ready")
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      DASHBOARD_WORKFLOW_PATH,
      OPERATIONAL_DASHBOARD_PATH,
    ])

    await requestDashboardFinancialState(fetchMock)
    expect(fetchMock.mock.calls.filter(([url]) => url === DASHBOARD_WORKFLOW_PATH)).toHaveLength(2)
    expect(fetchMock.mock.calls.filter(([url]) => url === OPERATIONAL_DASHBOARD_PATH)).toHaveLength(
      1
    )
  })

  it("keeps operational failure independent from ready snapshot financial data", async () => {
    const snapshotFetch = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ status: "ready", refresh, data: dashboardSnapshotFixture }))
    const operationalFetch = vi.fn<typeof fetch>().mockRejectedValue(new Error("offline"))

    const [financial, operational] = await Promise.all([
      requestDashboardFinancialState(snapshotFetch),
      requestOperationalDashboardState(operationalFetch),
    ])

    expect(financial.status).toBe("ready")
    expect(operational).toEqual({
      status: "error",
      message: "Provozní přehled se nepodařilo načíst.",
    })
  })

  it("keeps orchestration thin and maintains separate state and error branches", async () => {
    const page = await readFile(path.join(process.cwd(), "src/app/dashboard/page.tsx"), "utf8")

    expect(page).toContain("requestDashboardFinancialState")
    expect(page).toContain("requestOperationalDashboardState")
    expect(page).toContain("financialState")
    expect(page).toContain("operationalState")
    expect(page).toContain("initialLoadStarted")
    expect(page).toContain('status === "empty"')
    expect(page).toContain('status === "ready"')
    expect(page).toContain("Zatím nemáte žádný účet")
    expect(page).toContain("<SnapshotSummaryCards")
    expect(page).toContain("<SnapshotAccountCards")
    expect(page).toContain("<SnapshotAssetAllocationChart")
    expect(page).toContain("<SnapshotTopPositions")
    expect(page).toContain("<OperationalDashboardSections")
    expect(page).not.toMatch(/\bfetch\s*\(/)
    expect(page).not.toContain("/api/rates")
    expect(page).not.toContain("recalculate")
    expect(page).not.toMatch(/\b(?:token|manifest|snapshotId|accountId)\b/)
    expect(page).not.toMatch(
      /cashValueCzk|portfolioValueCzk|liabilitiesValueCzk|netWorthCzk|accountBalances/
    )
  })
})
