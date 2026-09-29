import { getServerSession } from "next-auth"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { POST as dashboardWorkflowPost } from "@/app/api/snapshot-workflow/dashboard/route"
import { POST as portfolioWorkflowPost } from "@/app/api/snapshot-workflow/portfolio/route"
import { requestDashboardFinancialState } from "@/modules/dashboard/snapshot-dashboard-client"
import { buildSnapshotDashboardModel } from "@/modules/dashboard/snapshot-dashboard-model"
import { requestPortfolioPageState } from "@/modules/portfolio/snapshot-page-client"
import { formatSnapshotAmount } from "@/modules/portfolio/snapshot-page-format"
import { buildPortfolioPageModel } from "@/modules/portfolio/snapshot-page-model"
import type {
  DashboardSnapshotData,
  PortfolioSnapshotData,
} from "@/modules/python-api/snapshot-workflow-contract"

vi.mock("next-auth", () => ({ getServerSession: vi.fn() }))
vi.mock("@/lib/auth", () => ({ authOptions: { providers: [] } }))

const BACKEND_URL = "https://python.r10e2.test"
const getSession = vi.mocked(getServerSession)
const ENVIRONMENT_KEYS = [
  "PYTHON_BACKEND_URL",
  "INTERNAL_AUTH_SECRET",
  "INTERNAL_AUTH_ISSUER",
  "INTERNAL_AUTH_AUDIENCE",
] as const
const previousEnvironment = Object.fromEntries(
  ENVIRONMENT_KEYS.map((key) => [key, process.env[key]])
)

const summary = {
  cashValue: "0.000000",
  cashByCurrency: [],
  investmentValue: "0.000000",
  investmentCostBasis: "0.000000",
  liabilitiesValue: "1800.000000",
  totalValue: "-1800.000000",
  netDepositsValue: "0.000000",
  netDepositsByCurrency: [],
  realizedPnlValue: "0.000000",
  unrealizedPnlValue: "0.000000",
  feesValue: "0.000000",
  taxesValue: "0.000000",
  positionCount: 0,
}

const portfolio: PortfolioSnapshotData = {
  asOf: "2032-08-02T12:30:00.000",
  baselineTimestamp: "2032-08-02T00:00:00.000",
  historyAnchorSnapshotId: "net-worth-baseline",
  valuationTimestamp: "2032-08-02T12:29:00.000",
  isStale: false,
  currency: "CZK",
  calculationVersion: 7,
  summary: { ...summary, accountCount: 1 },
  accounts: [
    {
      baselineSnapshotId: "companion-eur",
      primaryBaselineSnapshotId: "primary-czk",
      currency: "EUR",
      account: {
        accountId: "loan-eur",
        name: "EUR loan",
        accountType: "loan",
        currency: "EUR",
      },
      summary: {
        ...summary,
        liabilitiesValue: "75.000000",
        totalValue: "-75.000000",
      },
      positions: [],
    },
  ],
  aggregatePositions: [],
}

const dashboard: DashboardSnapshotData = {
  asOf: portfolio.asOf,
  baselineTimestamp: portfolio.baselineTimestamp,
  historyAnchorSnapshotId: portfolio.historyAnchorSnapshotId,
  valuationTimestamp: portfolio.valuationTimestamp,
  isStale: portfolio.isStale,
  currency: "CZK",
  calculationVersion: 7,
  summary: {
    totalValue: "-1800.000000",
    assetsValue: "0.000000",
    liabilitiesValue: "1800.000000",
    cashValue: "0.000000",
    investmentValue: "0.000000",
    investmentCostBasis: "0.000000",
    unrealizedPnlValue: "0.000000",
    realizedPnlValue: "0.000000",
    netDepositsValue: "0.000000",
    feesValue: "0.000000",
    taxesValue: "0.000000",
    accountCount: 1,
    investmentAccountCount: 0,
    liabilityAccountCount: 1,
    positionCount: 0,
  },
  accounts: [
    {
      accountId: "loan-eur",
      baselineSnapshotId: "companion-eur",
      primaryBaselineSnapshotId: "primary-czk",
      name: "EUR loan",
      accountType: "loan",
      accountCurrency: "EUR",
      outputCurrency: "EUR",
      totalValue: "-75.000000",
      cashValue: "0.000000",
      investmentValue: "0.000000",
      liabilitiesValue: "75.000000",
      netDepositsValue: "0.000000",
      unrealizedPnlValue: "0.000000",
      positionCount: 0,
    },
  ],
  assetTypeAllocations: [],
  topPositions: [],
}

function response(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  process.env.PYTHON_BACKEND_URL = BACKEND_URL
  process.env.INTERNAL_AUTH_SECRET = "r10e2-internal-auth-secret-32-characters"
  process.env.INTERNAL_AUTH_ISSUER = "finance-app-next"
  process.env.INTERNAL_AUTH_AUDIENCE = "finance-app-python"
  getSession.mockResolvedValue({
    user: { id: "r10e2-user", email: "r10e2@example.test" },
    expires: "2037-01-01",
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  for (const key of ENVIRONMENT_KEYS) {
    const previous = previousEnvironment[key]
    if (previous === undefined) delete process.env[key]
    else process.env[key] = previous
  }
})

describe("R10-E2 canonical current MONEY", () => {
  it("accepts mixed-currency FastAPI payloads through authenticated routes and UI models", async () => {
    const requests: string[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const url = new Request(input).url
        requests.push(url)
        if (url === `${BACKEND_URL}/api/v1/portfolio/published`) return response(portfolio)
        if (url === `${BACKEND_URL}/api/v1/dashboard/published`) return response(dashboard)
        throw new Error("Unexpected request")
      })
    )
    const portfolioBrowserFetch = vi.fn<typeof fetch>(async () => portfolioWorkflowPost())
    const dashboardBrowserFetch = vi.fn<typeof fetch>(async () => dashboardWorkflowPost())

    const portfolioState = await requestPortfolioPageState(portfolioBrowserFetch)
    const dashboardState = await requestDashboardFinancialState(dashboardBrowserFetch)

    if (portfolioState.status !== "ready" || dashboardState.status !== "ready") {
      throw new Error(
        `Expected canonical payloads to pass runtime validation: ${JSON.stringify({ portfolioState, dashboardState, requests })}`
      )
    }
    const portfolioModel = buildPortfolioPageModel(portfolioState.data)
    const dashboardModel = buildSnapshotDashboardModel(dashboardState.data)
    expect(portfolioModel.aggregate.summary.liabilitiesValue).toBe("1800.000000")
    expect(portfolioModel.accounts[0]?.currency).toBe("EUR")
    expect(portfolioModel.accounts[0]?.summary.liabilitiesValue).toBe("75.000000")
    expect(dashboardModel.summary.liabilitiesValue).toBe("1800.000000")
    expect(dashboardModel.accounts[0]?.liabilitiesValue).toBe("75.000000")

    expect(
      formatSnapshotAmount(dashboardModel.summary.liabilitiesValue, dashboardModel.currency)
    ).toBe("1\u00a0800,00 CZK")
    expect(
      formatSnapshotAmount(
        dashboardModel.accounts[0]!.liabilitiesValue,
        dashboardModel.accounts[0]!.accountCurrency
      )
    ).toBe("75,00 EUR")
    expect(requests).toEqual([
      `${BACKEND_URL}/api/v1/portfolio/published`,
      `${BACKEND_URL}/api/v1/dashboard/published`,
    ])
    expect(JSON.stringify(requests)).not.toMatch(/snapshot-refresh|recalculate|\/api\/rates/)
  })

  it.each([
    "1800",
    "1800.0",
    "1800.0000000",
    "1800.00000000000000",
    "1.8e3",
    "+1800.000000",
    "NaN",
    "Infinity",
    "1000000000000.000000",
  ])("keeps rejecting noncanonical MONEY %s", async (invalid) => {
    const malformed = structuredClone(portfolio)
    malformed.summary.liabilitiesValue = invalid
    const serverFetch = vi.fn<typeof fetch>().mockResolvedValue(response(malformed))
    vi.stubGlobal("fetch", serverFetch)

    const result = await requestPortfolioPageState(
      vi.fn<typeof fetch>(async () => portfolioWorkflowPost())
    )

    expect(result).toMatchObject({ status: "error", code: "python_api_contract_error" })
    expect(serverFetch).toHaveBeenCalledOnce()
  })
})
