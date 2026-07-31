import { readFile } from "node:fs/promises"
import path from "node:path"

import { jwtVerify } from "jose"
import { getServerSession } from "next-auth"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { POST as portfolioWorkflowPost } from "@/app/api/snapshot-workflow/portfolio/route"
import {
  PORTFOLIO_WORKFLOW_PATH,
  requestPortfolioPageState,
} from "@/modules/portfolio/snapshot-page-client"
import {
  buildPortfolioPageModel,
  selectPortfolioAccountView,
} from "@/modules/portfolio/snapshot-page-model"
import { portfolioSnapshotFixture } from "@/test/portfolio-snapshot-fixture"

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}))

vi.mock("@/lib/auth", () => ({
  authOptions: { providers: [] },
}))

const ROOT = process.cwd()
const BACKEND_URL = "https://python.audit.test"
const SECRET = "5m-final-browser-flow-secret-32-characters"
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
  netWorthSnapshotId: "net-worth-portfolio-audit",
  netWorthStatus: "created",
  timestamp: "2032-08-02T00:00:00.000",
  granularity: "day",
  currency: "EUR",
  calculationVersion: 7,
  accounts: [
    { accountId: "account-a", snapshotId: "snapshot-a" },
    { accountId: "account-b", snapshotId: "snapshot-b" },
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

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function browserFetchAdapter() {
  return vi.fn<typeof fetch>(async (input, init) => {
    expect(input).toBe(PORTFOLIO_WORKFLOW_PATH)
    expect(init).toEqual({ method: "POST", cache: "no-store" })
    return portfolioWorkflowPost()
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
    user: { id: "portfolio-audit-user", email: "portfolio-audit@example.test" },
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

describe("in-process portfolio browser flow", () => {
  it("connects browser, Next route, real workflow, FastAPI transport, and page model", async () => {
    const portfolio = portfolioSnapshotFixture()
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
      expect(payload.sub).toBe("portfolio-audit-user")
      expect(payload.email).toBe("portfolio-audit@example.test")
      tokenIds.push(String(payload.jti))
      expect(request.headers.has("Cookie")).toBe(false)

      if (request.url === `${BACKEND_URL}/api/v1/snapshot-refresh/recalculate`) {
        expect(request.method).toBe("POST")
        expect(await request.text()).toBe("")
        return jsonResponse(REFRESH)
      }
      if (request.url === `${BACKEND_URL}/api/v1/portfolio/snapshot`) {
        const body = await request.text()
        fastApiBodies.push(body)
        expect(body).toBe(JSON.stringify(MANIFEST))
        return jsonResponse(portfolio)
      }
      throw new Error("Unexpected FastAPI request.")
    })
    vi.stubGlobal("fetch", serverFetch)
    const browserFetch = browserFetchAdapter()

    const state = await requestPortfolioPageState(browserFetch)

    expect(browserFetch).toHaveBeenCalledTimes(1)
    expect(getSession).toHaveBeenCalledTimes(1)
    expect(serverFetch).toHaveBeenCalledTimes(2)
    expect(requestUrls).toEqual([
      `${BACKEND_URL}/api/v1/snapshot-refresh/recalculate`,
      `${BACKEND_URL}/api/v1/portfolio/snapshot`,
    ])
    expect(tokens).toHaveLength(2)
    expect(new Set(tokens).size).toBe(2)
    expect(new Set(tokenIds).size).toBe(2)
    expect(fastApiBodies).toEqual([JSON.stringify(MANIFEST)])
    expect(state.status).toBe("ready")
    if (state.status !== "ready") throw new Error("Expected ready state.")
    expect(state.data).toEqual(portfolio)
    expect(state.refresh).not.toHaveProperty("accounts")
    expect(JSON.stringify(state)).not.toContain(SECRET)
    for (const token of tokens) expect(JSON.stringify(state)).not.toContain(token)

    const model = buildPortfolioPageModel(state.data)
    expect(model.aggregate.summary).toBe(state.data.summary)
    expect(model.aggregate.summary.totalValue).toBe("777.123456")
    expect(model.accounts[0]?.summary).toBe(state.data.accounts[0]?.summary)
    expect(model.accounts[0]?.positions[0]?.position.value).toBe("123.456789")

    const selected = selectPortfolioAccountView(model, "account-b")
    expect(selected?.summary).toBe(state.data.accounts[1]?.summary)
    expect(browserFetch).toHaveBeenCalledTimes(1)
    expect(serverFetch).toHaveBeenCalledTimes(2)
  })

  it("returns empty after one FastAPI request and never performs a 5L or legacy read", async () => {
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

    const state = await requestPortfolioPageState(browserFetch)

    expect(state.status).toBe("empty")
    expect(state).not.toHaveProperty("data")
    expect(state).not.toHaveProperty("manifest")
    expect(state).not.toHaveProperty("selector")
    expect(browserFetch).toHaveBeenCalledTimes(1)
    expect(serverFetch).toHaveBeenCalledTimes(1)
    expect(JSON.stringify(browserFetch.mock.calls)).not.toMatch(
      /\/api\/portfolio(?:\?|$)|\/api\/rates|latest|recalculate/
    )
  })

  it("maps a FastAPI failure to a safe page error without retry or fallback", async () => {
    const serverFetch = vi.fn<typeof fetch>(async () => {
      throw new Error("secret token cookie stack trace")
    })
    vi.stubGlobal("fetch", serverFetch)
    const browserFetch = browserFetchAdapter()

    const state = await requestPortfolioPageState(browserFetch)

    expect(state).toMatchObject({ status: "error", code: "python_api_unavailable" })
    expect(JSON.stringify(state)).not.toMatch(/secret|token|cookie|stack trace/)
    expect(browserFetch).toHaveBeenCalledTimes(1)
    expect(serverFetch).toHaveBeenCalledTimes(1)
  })
})

describe("portfolio financial authority and history isolation", () => {
  it("preserves representative Decimal strings without financial recomputation", () => {
    const portfolio = portfolioSnapshotFixture()
    const values = [
      "0",
      "-0.000001",
      "123456789012.123456",
      "999999999999.999999",
      "0.3333",
      "100.0000",
    ]
    portfolio.summary.cashValue = values[0]
    portfolio.summary.realizedPnlValue = values[1]
    portfolio.summary.totalValue = values[2]
    portfolio.summary.investmentValue = values[3]
    portfolio.summary.unrealizedPnlValue = values[4]
    portfolio.summary.investmentCostBasis = values[5]

    const model = buildPortfolioPageModel(portfolio)

    expect(model.aggregate.summary).toBe(portfolio.summary)
    expect([
      model.aggregate.summary.cashValue,
      model.aggregate.summary.realizedPnlValue,
      model.aggregate.summary.totalValue,
      model.aggregate.summary.investmentValue,
      model.aggregate.summary.unrealizedPnlValue,
      model.aggregate.summary.investmentCostBasis,
    ]).toEqual(values)
  })

  it("keeps current finance free of legacy, history, Prisma, price, FX, and calculations", async () => {
    const files = [
      "src/app/portfolio/page.tsx",
      "src/modules/portfolio/snapshot-page-client.ts",
      "src/modules/portfolio/snapshot-page-model.ts",
      "src/modules/portfolio/SnapshotHoldingsTable.tsx",
    ]
    const content = (
      await Promise.all(files.map((file) => readFile(path.join(ROOT, file), "utf8")))
    ).join("\n")

    expect(content).not.toMatch(
      /GET \/api\/portfolio|\/api\/rates|snapshots\/recalculate|latestHistoryPoint|history positions|history allocation/i
    )
    expect(content).not.toMatch(/\b(?:Prisma|YAHOO|FX service|price provider)\b/i)
    expect(content).not.toMatch(/\b(?:Number|parseFloat|parseInt|Math\.round)\s*\(/)
    expect(content).not.toContain(".toFixed(")
    expect(content).not.toContain(".reduce(")
  })

  it("isolates the only portfolio Decimal conversion at the chart leaf", async () => {
    const chart = await readFile(
      path.join(ROOT, "src/modules/portfolio/SnapshotAllocationPie.tsx"),
      "utf8"
    )

    expect(chart.match(/\bNumber\s*\(/g)).toHaveLength(1)
    expect(chart).toContain("Presentation-only conversion at the Recharts leaf boundary")
    expect(chart).toContain("exactAllocation: position.allocationPct")
    expect(chart).not.toContain(".sort(")
    expect(chart).not.toContain(".reduce(")
  })

  it("keeps history chart-only and unable to overwrite current page state", async () => {
    const page = await readFile(path.join(ROOT, "src/app/portfolio/page.tsx"), "utf8")
    const history = await readFile(
      path.join(ROOT, "src/modules/portfolio/snapshot-history-client.ts"),
      "utf8"
    )

    expect(history).toContain("/api/portfolio/history?")
    expect(page).toContain("<PortfolioLineChart")
    expect(page).not.toContain("latestHistoryPoint")
    expect(page).not.toContain("activeHistoryPoint")
    expect(page).not.toMatch(/history.*(?:summary|positions|allocation|accounts|currency)/i)
  })
})
