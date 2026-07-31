import { readFile } from "node:fs/promises"
import path from "node:path"

import { jwtVerify } from "jose"
import { getServerSession } from "next-auth"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { POST as dashboardWorkflowPost } from "@/app/api/snapshot-workflow/dashboard/route"
import {
  DASHBOARD_WORKFLOW_PATH,
  requestDashboardFinancialState,
} from "@/modules/dashboard/snapshot-dashboard-client"
import {
  OPERATIONAL_DASHBOARD_PATH,
  requestOperationalDashboardState,
} from "@/modules/dashboard/operational-dashboard-client"
import { buildSnapshotDashboardModel } from "@/modules/dashboard/snapshot-dashboard-model"
import { dashboardSnapshotFixture } from "@/test/dashboard-snapshot-fixture"

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}))

vi.mock("@/lib/auth", () => ({
  authOptions: { providers: [] },
}))

const ROOT = process.cwd()
const BACKEND_URL = "https://python.audit.test"
const SECRET = "5m-final-dashboard-flow-secret-32-characters"
const KEY = new TextEncoder().encode(SECRET)
const getSession = vi.mocked(getServerSession)
const ENVIRONMENT_KEYS = [
  "PYTHON_BACKEND_URL",
  "INTERNAL_AUTH_SECRET",
  "INTERNAL_AUTH_ISSUER",
  "INTERNAL_AUTH_AUDIENCE",
  "INTERNAL_AUTH_TOKEN_TTL_SECONDS",
  "PYTHON_API_TIMEOUT_MS",
] as const
const previousEnvironment = Object.fromEntries(
  ENVIRONMENT_KEYS.map((key) => [key, process.env[key]])
)

const REFRESH = {
  netWorthSnapshotId: "net-worth-dashboard-audit",
  netWorthStatus: "created",
  timestamp: dashboardSnapshotFixture.timestamp,
  granularity: dashboardSnapshotFixture.granularity,
  currency: dashboardSnapshotFixture.currency,
  calculationVersion: dashboardSnapshotFixture.calculationVersion,
  accounts: [
    { accountId: "account-a", snapshotId: "snapshot-a" },
    { accountId: "account-z", snapshotId: "snapshot-z" },
  ],
  refreshAccountCount: 2,
  reuseOnlyAccountCount: 0,
  createdAccountSnapshotCount: 2,
  replayedAccountSnapshotCount: 0,
  reusedAccountSnapshotCount: 0,
  selectedAccountSnapshotCount: 2,
}

const MANIFEST = {
  timestamp: REFRESH.timestamp,
  granularity: REFRESH.granularity,
  currency: REFRESH.currency,
  calculationVersion: REFRESH.calculationVersion,
  accounts: REFRESH.accounts,
}

const OPERATIONAL_PAYLOAD = {
  summary: {
    cashValueCzk: 999_999,
    portfolioValueCzk: 888_888,
    liabilitiesValueCzk: -777_777,
    netWorthCzk: 666_666,
    currentMonthIncomeCzk: 1200,
    currentMonthExpenseCzk: 450,
    currentMonthNetCzk: 750,
  },
  accountBalances: [{ accountId: "legacy-account", totalCzk: 123 }],
  budget: null,
  expenseByCategory: [],
  monthlyTrends: [],
  recentTransactions: [],
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function browserFetchAdapter() {
  return vi.fn<typeof fetch>(async (input, init) => {
    expect(input).toBe(DASHBOARD_WORKFLOW_PATH)
    expect(init).toEqual({ method: "POST", cache: "no-store" })
    return dashboardWorkflowPost()
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  process.env.PYTHON_BACKEND_URL = BACKEND_URL
  process.env.INTERNAL_AUTH_SECRET = SECRET
  process.env.INTERNAL_AUTH_ISSUER = "finance-app-next"
  process.env.INTERNAL_AUTH_AUDIENCE = "finance-app-python"
  process.env.INTERNAL_AUTH_TOKEN_TTL_SECONDS = "60"
  process.env.PYTHON_API_TIMEOUT_MS = "30000"
  getSession.mockResolvedValue({
    user: { id: "dashboard-audit-user", email: "dashboard-audit@example.test" },
    expires: "2037-01-01",
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  for (const key of ENVIRONMENT_KEYS) {
    const previous = previousEnvironment[key]
    if (previous === undefined) {
      delete process.env[key]
    } else {
      process.env[key] = previous
    }
  }
})

describe("in-process dashboard browser flow", () => {
  it("connects browser, Next route, real workflow, FastAPI transport, and page model", async () => {
    const dashboard = structuredClone(dashboardSnapshotFixture)
    const tokens: string[] = []
    const tokenIds: string[] = []
    const fastApiBodies: string[] = []
    const requestUrls: string[] = []
    const serverFetch = vi.fn<typeof fetch>(async (input, init) => {
      const request = new Request(input, init)
      requestUrls.push(request.url)
      const authorization = request.headers.get("Authorization")
      expect(authorization).toMatch(/^Bearer /)
      const token = authorization?.slice("Bearer ".length) ?? ""
      tokens.push(token)
      const { payload } = await jwtVerify(token, KEY, {
        algorithms: ["HS256"],
        issuer: "finance-app-next",
        audience: "finance-app-python",
      })
      expect(payload.sub).toBe("dashboard-audit-user")
      expect(payload.email).toBe("dashboard-audit@example.test")
      tokenIds.push(String(payload.jti))
      expect(request.headers.has("Cookie")).toBe(false)

      if (request.url === `${BACKEND_URL}/api/v1/snapshot-refresh/recalculate`) {
        expect(await request.text()).toBe("")
        return jsonResponse(REFRESH)
      }
      if (request.url === `${BACKEND_URL}/api/v1/dashboard/snapshot`) {
        const body = await request.text()
        fastApiBodies.push(body)
        expect(body).toBe(JSON.stringify(MANIFEST))
        return jsonResponse(dashboard)
      }
      throw new Error("Unexpected FastAPI request.")
    })
    vi.stubGlobal("fetch", serverFetch)
    const browserFetch = browserFetchAdapter()

    const state = await requestDashboardFinancialState(browserFetch)

    expect(browserFetch).toHaveBeenCalledTimes(1)
    expect(getSession).toHaveBeenCalledTimes(1)
    expect(serverFetch).toHaveBeenCalledTimes(2)
    expect(requestUrls).toEqual([
      `${BACKEND_URL}/api/v1/snapshot-refresh/recalculate`,
      `${BACKEND_URL}/api/v1/dashboard/snapshot`,
    ])
    expect(tokens).toHaveLength(2)
    expect(new Set(tokens).size).toBe(2)
    expect(new Set(tokenIds).size).toBe(2)
    expect(fastApiBodies).toEqual([JSON.stringify(MANIFEST)])
    expect(state.status).toBe("ready")
    if (state.status !== "ready") throw new Error("Expected ready state.")
    expect(state.refresh).not.toHaveProperty("accounts")
    expect(JSON.stringify(state)).not.toContain(SECRET)
    for (const token of tokens) expect(JSON.stringify(state)).not.toContain(token)

    const model = buildSnapshotDashboardModel(state.data)
    expect(model.summary).toBe(state.data.summary)
    expect(model.accounts).toBe(state.data.accounts)
    expect(model.assetTypeAllocations).toBe(state.data.assetTypeAllocations)
    expect(model.topPositions).toBe(state.data.topPositions)
    expect(model.summary.totalValue).toBe("98765432109876543210.123456")
    expect(model.accounts.map(({ accountId }) => accountId)).toEqual(["account-z", "account-a"])
    expect(model.topPositions.map(({ symbol }) => symbol)).toEqual(["ZZZ", "AAA"])
  })

  it("returns empty after one FastAPI request while operational data remains independent", async () => {
    const emptyRefresh = {
      ...REFRESH,
      accounts: [],
      refreshAccountCount: 0,
      createdAccountSnapshotCount: 0,
      selectedAccountSnapshotCount: 0,
    }
    const serverFetch = vi.fn<typeof fetch>(async (input, init) => {
      const request = new Request(input, init)
      expect(request.url).toBe(`${BACKEND_URL}/api/v1/snapshot-refresh/recalculate`)
      return jsonResponse(emptyRefresh)
    })
    vi.stubGlobal("fetch", serverFetch)
    const browserFetch = browserFetchAdapter()
    const operationalFetch = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(OPERATIONAL_PAYLOAD))

    const [financial, operational] = await Promise.all([
      requestDashboardFinancialState(browserFetch),
      requestOperationalDashboardState(operationalFetch),
    ])

    expect(financial.status).toBe("empty")
    expect(financial).not.toHaveProperty("data")
    expect(financial).not.toHaveProperty("manifest")
    expect(financial).not.toHaveProperty("selector")
    expect(operational).toEqual({
      status: "ready",
      data: {
        currentMonth: { income: 1200, expenses: 450, net: 750 },
        budget: null,
        expenseByCategory: [],
        monthlyTrends: [],
        recentTransactions: [],
      },
    })
    expect(browserFetch).toHaveBeenCalledTimes(1)
    expect(serverFetch).toHaveBeenCalledTimes(1)
    expect(operationalFetch).toHaveBeenCalledTimes(1)
  })

  it("keeps snapshot and operational errors independent without retry or fallback", async () => {
    const serverFetch = vi.fn<typeof fetch>(async () => {
      throw new Error("secret backend URL token stack trace")
    })
    vi.stubGlobal("fetch", serverFetch)
    const browserFetch = browserFetchAdapter()
    const operationalFetch = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(OPERATIONAL_PAYLOAD))

    const [financial, operational] = await Promise.all([
      requestDashboardFinancialState(browserFetch),
      requestOperationalDashboardState(operationalFetch),
    ])

    expect(financial).toMatchObject({ status: "error", code: "python_api_unavailable" })
    expect(JSON.stringify(financial)).not.toMatch(/secret|token|stack trace|python\.audit/)
    expect(operational.status).toBe("ready")
    expect(JSON.stringify(operational)).not.toMatch(
      /cashValueCzk|portfolioValueCzk|liabilitiesValueCzk|netWorthCzk|accountBalances/
    )
    expect(browserFetch).toHaveBeenCalledTimes(1)
    expect(serverFetch).toHaveBeenCalledTimes(1)
    expect(operationalFetch).toHaveBeenCalledTimes(1)
  })

  it("refreshes financial data without adding an operational request", async () => {
    const serverFetch = vi.fn<typeof fetch>(async (input, init) => {
      const request = new Request(input, init)
      if (request.url.endsWith("/snapshot-refresh/recalculate")) return jsonResponse(REFRESH)
      if (request.url.endsWith("/dashboard/snapshot")) {
        return jsonResponse(dashboardSnapshotFixture)
      }
      throw new Error("Unexpected FastAPI request.")
    })
    vi.stubGlobal("fetch", serverFetch)
    const browserFetch = browserFetchAdapter()
    const operationalFetch = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(OPERATIONAL_PAYLOAD))

    await Promise.all([
      requestDashboardFinancialState(browserFetch),
      requestOperationalDashboardState(operationalFetch),
    ])
    await requestDashboardFinancialState(browserFetch)

    expect(browserFetch).toHaveBeenCalledTimes(2)
    expect(serverFetch).toHaveBeenCalledTimes(4)
    expect(operationalFetch).toHaveBeenCalledTimes(1)
  })
})

describe("dashboard financial and operational authority", () => {
  it("preserves representative Decimal strings without creating a summary", () => {
    const dashboard = structuredClone(dashboardSnapshotFixture)
    const values = [
      "0",
      "-0.000001",
      "123456789012.123456",
      "999999999999.999999",
      "0.3333",
      "100.0000",
    ]
    dashboard.summary.cashValue = values[0]
    dashboard.summary.realizedPnlValue = values[1]
    dashboard.summary.totalValue = values[2]
    dashboard.summary.investmentValue = values[3]
    dashboard.summary.unrealizedPnlValue = values[4]
    dashboard.summary.investmentCostBasis = values[5]

    const model = buildSnapshotDashboardModel(dashboard)

    expect(model.summary).toBe(dashboard.summary)
    expect([
      model.summary.cashValue,
      model.summary.realizedPnlValue,
      model.summary.totalValue,
      model.summary.investmentValue,
      model.summary.unrealizedPnlValue,
      model.summary.investmentCostBasis,
    ]).toEqual(values)
  })

  it("physically narrows operational data and never maps snapshot metrics to cash flow", async () => {
    const operationalFetch = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(OPERATIONAL_PAYLOAD))

    const result = await requestOperationalDashboardState(operationalFetch)

    expect(result.status).toBe("ready")
    expect(JSON.stringify(result)).not.toMatch(
      /cashValueCzk|portfolioValueCzk|liabilitiesValueCzk|netWorthCzk|accountBalances|totalCzk|balances/
    )
    expect(JSON.stringify(result)).not.toMatch(
      /netDepositsValue|realizedPnlValue|unrealizedPnlValue|totalValue/
    )
    expect(operationalFetch).toHaveBeenCalledWith(OPERATIONAL_DASHBOARD_PATH, {
      method: "GET",
      cache: "no-store",
    })
  })

  it("keeps legacy finance and financial calculations out of snapshot presentation", async () => {
    const files = [
      "src/app/dashboard/page.tsx",
      "src/modules/dashboard/snapshot-dashboard-client.ts",
      "src/modules/dashboard/snapshot-dashboard-model.ts",
      "src/modules/dashboard/SnapshotSummaryCards.tsx",
      "src/modules/dashboard/SnapshotAccountCards.tsx",
      "src/modules/dashboard/SnapshotTopPositions.tsx",
    ]
    const content = (
      await Promise.all(files.map((file) => readFile(path.join(ROOT, file), "utf8")))
    ).join("\n")

    expect(content).not.toMatch(
      /\b(?:cashValueCzk|portfolioValueCzk|liabilitiesValueCzk|netWorthCzk|accountBalances|totalCzk|balances)\b/
    )
    expect(content).not.toMatch(/\b(?:Number|parseFloat|parseInt|Math\.round)\s*\(/)
    expect(content).not.toContain(".toFixed(")
    expect(content).not.toContain(".reduce(")
    expect(content).not.toMatch(/\b(?:Prisma|latest snapshot|price provider|FX service)\b/i)
  })

  it("isolates the only dashboard Decimal conversion at the chart leaf", async () => {
    const chart = await readFile(
      path.join(ROOT, "src/modules/dashboard/SnapshotAssetAllocationChart.tsx"),
      "utf8"
    )

    expect(chart.match(/\bNumber\s*\(/g)).toHaveLength(1)
    expect(chart).toContain("Presentation-only Decimal conversion required by Recharts")
    expect(chart).toContain("allocationPct")
    expect(chart).not.toContain(".sort(")
    expect(chart).not.toContain(".reduce(")
  })
})
