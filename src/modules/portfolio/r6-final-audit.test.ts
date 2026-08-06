import { readFile } from "node:fs/promises"
import { createRequire } from "node:module"
import path from "node:path"

import { jwtVerify } from "jose"
import { getServerSession } from "next-auth"
import { createElement } from "react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { POST as portfolioWorkflowPost } from "@/app/api/snapshot-workflow/portfolio/route"
import { SnapshotCurrencyBreakdown } from "@/modules/portfolio/SnapshotCurrencyBreakdown"
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

const { renderToStaticMarkup } = createRequire(import.meta.url)("react-dom/server") as {
  renderToStaticMarkup(node: ReactNode): string
}

const ROOT = process.cwd()
const BACKEND_URL = "https://python.r6-audit.test"
const SECRET = "r6-final-audit-secret-32-characters"
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
  netWorthSnapshotId: "net-worth-r6-audit",
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

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
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
    user: { id: "r6-audit-user", email: "r6-audit@example.test" },
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

describe("R6 browser-to-presentation acceptance", () => {
  it("preserves aggregate and account breakdowns through one browser and two FastAPI requests", async () => {
    const portfolio = portfolioSnapshotFixture()
    const requestUrls: string[] = []
    const tokens: string[] = []
    const serverFetch = vi.fn<typeof fetch>(async (input, init) => {
      const request = new Request(input, init)
      requestUrls.push(request.url)
      expect(request.headers.has("Cookie")).toBe(false)
      const authorization = request.headers.get("Authorization")
      expect(authorization).toMatch(/^Bearer /)
      const token = authorization?.slice("Bearer ".length) ?? ""
      tokens.push(token)
      const { payload } = await jwtVerify(token, KEY, {
        algorithms: ["HS256"],
        issuer: "finance-app-next",
        audience: "finance-app-python",
      })
      expect(payload.sub).toBe("r6-audit-user")

      if (request.url.endsWith("/api/v1/snapshot-refresh/recalculate")) {
        return jsonResponse(REFRESH)
      }
      if (request.url.endsWith("/api/v1/portfolio/snapshot")) {
        expect(await request.json()).toEqual({
          timestamp: REFRESH.timestamp,
          granularity: REFRESH.granularity,
          currency: REFRESH.currency,
          calculationVersion: REFRESH.calculationVersion,
          accounts: REFRESH.accounts,
        })
        return jsonResponse(portfolio)
      }
      throw new Error("Unexpected FastAPI request.")
    })
    vi.stubGlobal("fetch", serverFetch)
    const browserFetch = vi.fn<typeof fetch>(async (input, init) => {
      expect(input).toBe(PORTFOLIO_WORKFLOW_PATH)
      expect(init).toEqual({ method: "POST", cache: "no-store" })
      return portfolioWorkflowPost()
    })

    const state = await requestPortfolioPageState(browserFetch)

    expect(browserFetch).toHaveBeenCalledTimes(1)
    expect(serverFetch).toHaveBeenCalledTimes(2)
    expect(requestUrls).toEqual([
      `${BACKEND_URL}/api/v1/snapshot-refresh/recalculate`,
      `${BACKEND_URL}/api/v1/portfolio/snapshot`,
    ])
    expect(state.status).toBe("ready")
    if (state.status !== "ready") throw new Error("Expected ready portfolio state.")
    expect(state.data).toEqual(portfolio)
    expect(JSON.stringify(state)).not.toContain(SECRET)
    for (const token of tokens) expect(JSON.stringify(state)).not.toContain(token)

    const model = buildPortfolioPageModel(state.data)
    expect(model.aggregate.summary).toBe(state.data.summary)
    expect(model.aggregate.summary.cashByCurrency).toBe(state.data.summary.cashByCurrency)
    expect(model.aggregate.summary.netDepositsByCurrency).toBe(
      state.data.summary.netDepositsByCurrency
    )
    expect(model.aggregate.summary.cashByCurrency.map((item) => item.currency)).toEqual([
      "CZK",
      "EUR",
      "USD",
    ])
    expect(model.aggregate.summary.cashByCurrency[2]?.amount).toBe("-50.000000")

    const selected = selectPortfolioAccountView(model, "account-b")
    expect(selected?.summary).toBe(state.data.accounts[1]?.summary)
    expect(selected?.summary.cashByCurrency).toBe(state.data.accounts[1]?.summary.cashByCurrency)
    expect(selected?.summary.netDepositsByCurrency).toBe(
      state.data.accounts[1]?.summary.netDepositsByCurrency
    )
    expect(browserFetch).toHaveBeenCalledTimes(1)
    expect(serverFetch).toHaveBeenCalledTimes(2)
  })

  it("renders exact negative, zero, long, and empty evidence semantically", () => {
    const items = [
      { currency: "CZK", amount: "123456789012.123456" },
      { currency: "EUR", amount: "0.000000" },
      { currency: "USD", amount: "-50.000000" },
    ] as const
    const output = renderToStaticMarkup(
      createElement(SnapshotCurrencyBreakdown, {
        title: "Hotovost podle měny",
        emptyMessage: "Žádná hotovost.",
        items,
      })
    )

    expect(output).toContain("<section")
    expect(output).toContain('aria-labelledby="')
    expect(output).toContain("<h2")
    expect(output).toContain("<dl")
    expect(output).toContain("<dt")
    expect(output).toContain("<dd")
    expect(output.indexOf("CZK")).toBeLessThan(output.indexOf("EUR"))
    expect(output.indexOf("EUR")).toBeLessThan(output.indexOf("USD"))
    expect(output).toContain("123")
    expect(output).toContain("123456")
    expect(output).toContain("0,000000")
    expect(output).toContain("-50,000000")

    const empty = renderToStaticMarkup(
      createElement(SnapshotCurrencyBreakdown, {
        title: "Čisté vklady podle měny",
        emptyMessage: "Žádné čisté vklady.",
        items: [],
      })
    )
    expect(empty).toContain("Žádné čisté vklady.")
    expect(empty).not.toContain("<dl")
    expect(empty).not.toContain("<dt")
  })
})

describe("R6 production inventory", () => {
  it("contains no frontend financial calculation, FX, aggregation, or fallback", async () => {
    const auditedFiles = [
      "src/app/portfolio/page.tsx",
      "src/modules/portfolio/snapshot-page-model.ts",
      "src/modules/portfolio/SnapshotCurrencyBreakdown.tsx",
      "src/modules/portfolio/SnapshotHoldingsTable.tsx",
    ]
    const content = (
      await Promise.all(auditedFiles.map((file) => readFile(path.join(ROOT, file), "utf8")))
    ).join("\n")

    expect(content).not.toMatch(/\b(?:Number|parseFloat|parseInt)\s*\(/)
    expect(content).not.toMatch(/\bMath\./)
    for (const forbidden of [
      ".toFixed(",
      ".reduce(",
      ".sort(",
      "new Map(",
      "Object.fromEntries(",
      "/api/rates",
    ]) {
      expect(content).not.toContain(forbidden)
    }
    expect(content).not.toMatch(/\b(?:legacy portfolio|latest FX)\b/i)
    expect(content).toContain("view.summary.cashValue")
    expect(content).toContain("view.summary.netDepositsValue")
    expect(content).toContain("view.summary.cashByCurrency")
    expect(content).toContain("view.summary.netDepositsByCurrency")
  })

  it("keeps history chart-only and dashboard production untouched", async () => {
    const page = await readFile(path.join(ROOT, "src/app/portfolio/page.tsx"), "utf8")
    const history = await readFile(
      path.join(ROOT, "src/modules/portfolio/snapshot-history-client.ts"),
      "utf8"
    )
    const dashboard = await readFile(path.join(ROOT, "src/app/dashboard/page.tsx"), "utf8")

    expect(history).toContain("/api/portfolio/history?")
    expect(page).toContain("<PortfolioLineChart")
    expect(page).not.toContain("latestHistoryPoint")
    expect(page).not.toContain("activeHistoryPoint")
    expect(page).not.toMatch(/history.*(?:summary|cashByCurrency|netDepositsByCurrency)/i)
    expect(dashboard).not.toContain("cashByCurrency")
    expect(dashboard).not.toContain("netDepositsByCurrency")
    expect(page).toContain("aria-pressed={selectedAccountId === null}")
    expect(page).toContain("grid-cols-1")
  })
})
