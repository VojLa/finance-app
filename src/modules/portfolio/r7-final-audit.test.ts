import { readdir, readFile } from "node:fs/promises"
import path from "node:path"

import { jwtVerify } from "jose"
import { getServerSession } from "next-auth"
import { NextRequest } from "next/server"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { GET as portfolioHistoryGet } from "@/app/api/portfolio/history/route"
import { buildPortfolioHistoryChartPoints } from "@/components/charts/portfolio-history-chart"
import {
  requestPortfolioHistory,
  startPortfolioHistoryRequest,
} from "@/modules/portfolio/snapshot-history-client"
import {
  buildPortfolioPageModel,
  selectPortfolioAccountView,
} from "@/modules/portfolio/snapshot-page-model"
import type { SnapshotPortfolioHistoryRange } from "@/modules/portfolio/snapshot-history-contract"
import { portfolioSnapshotFixture } from "@/test/portfolio-snapshot-fixture"

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}))

vi.mock("@/lib/auth", () => ({
  authOptions: { providers: [] },
}))

const ROOT = process.cwd()
const BACKEND_URL = "https://python.r7-final.test"
const SECRET = "r7-final-browser-secret-with-32-characters"
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

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

async function filesUnder(relativePath: string): Promise<string[]> {
  const directory = path.join(ROOT, relativePath)
  const entries = await readdir(directory, { withFileTypes: true })
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const child = path.join(relativePath, entry.name).replaceAll("\\", "/")
      return entry.isDirectory() ? filesUnder(child) : [child]
    })
  )
  return nested.flat()
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
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
    user: { id: "r7-audit-user", email: "r7-audit@example.test" },
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

describe("R7 checkout-portable production inventory", () => {
  it("proves the active route-to-chart call graph and legacy inactivity", async () => {
    const route = await source("src/app/api/portfolio/history/route.ts")
    const transport = await source("src/modules/python-api/server/portfolio-history.ts")
    const contract = await source("src/modules/portfolio/snapshot-history-contract.ts")
    const client = await source("src/modules/portfolio/snapshot-history-client.ts")
    const page = await source("src/app/portfolio/page.tsx")
    const chart = await source("src/components/charts/PortfolioLineChart.tsx")
    const chartProjection = await source("src/components/charts/portfolio-history-chart.ts")
    const barrel = await source("src/modules/snapshots/index.ts")
    const legacy = await source("src/modules/snapshots/service.ts")
    const active = `${route}\n${transport}\n${contract}\n${client}\n${page}\n${chart}\n${chartProjection}`

    expect(route).toContain("readSnapshotBackedPortfolioHistory")
    expect(transport).toContain("createAuthenticatedPythonTransport")
    expect(transport).toContain('client.GET("/api/v1/portfolio/history"')
    expect(contract).toContain('components["schemas"]["PortfolioHistoryResponse"]')
    expect(client).toContain("parseSnapshotPortfolioHistory")
    expect(page).toContain("startPortfolioHistoryRequest")
    expect(page).toContain("<PortfolioLineChart")
    expect(chart).toContain("buildPortfolioHistoryChartPoints")

    expect(active).not.toMatch(
      /@\/lib\/prisma|@\/lib\/accountAccess|@\/modules\/snapshots|@\/modules\/portfolio\/rates|getPortfolioSnapshotHistory|historical prices?|historical FX|\/api\/rates/
    )
    expect(barrel).not.toContain("getPortfolioSnapshotHistory")
    expect(legacy).toContain("export async function getPortfolioSnapshotHistory")

    const productionFiles = (await filesUnder("src"))
      .filter((file) => /\.(?:ts|tsx)$/.test(file))
      .filter((file) => !/\.test\.(?:ts|tsx)$/.test(file))
    const occurrences: string[] = []
    for (const file of productionFiles) {
      if ((await source(file)).includes("getPortfolioSnapshotHistory")) {
        occurrences.push(file)
      }
    }
    expect(occurrences).toEqual(["src/modules/snapshots/service.ts"])
  })

  it("proves exact browser validation, state isolation, and one chart conversion", async () => {
    const contract = await source("src/modules/portfolio/snapshot-history-contract.ts")
    const client = await source("src/modules/portfolio/snapshot-history-client.ts")
    const page = await source("src/app/portfolio/page.tsx")
    const chart = await source("src/components/charts/PortfolioLineChart.tsx")
    const chartProjection = await source("src/components/charts/portfolio-history-chart.ts")
    const historyChart = `${chart}\n${chartProjection}`

    expect(contract).toContain('const RESPONSE_KEYS = ["range", "currency", "points"]')
    expect(contract).toContain("const POINT_KEYS = [")
    expect(contract).toContain("const MAX_POINTS = 512")
    expect(contract).toContain("/^-?(?:0|[1-9]\\d{0,11})\\.\\d{6}$/")
    expect(contract).toContain("point.timestamp <= previousTimestamp")
    expect(client).not.toMatch(/\b(?:Number|parseFloat|parseInt)\s*\(|\.toFixed\(|\bMath\./)
    expect(client).not.toMatch(/\bas\s+Portfolio/)
    expect(client).toContain('status: "ready"')
    expect(client).toContain('status: "empty"')
    expect(client).toContain('status: "error"')

    expect(page).toContain('state.status === "ready" ? state.data.currency : null')
    expect(page).toContain('state.status === "ready" ? state.refresh.netWorthSnapshotId : null')
    expect(page).toContain("[historyCurrency, historyRange, historySnapshotId]")
    expect(page).not.toMatch(
      /\[historyCurrency,\s*historyRange,\s*historySnapshotId,\s*(?:selectedAccount|historyValueMode)/
    )
    expect(page).toContain("Historie celého portfolia")
    expect(page).toContain("Načítám historii portfolia…")
    expect(page).toContain('historyState.status === "empty"')
    expect(page).toContain('historyState.status === "error"')
    expect(page).toContain('historyState.status === "ready"')

    expect(historyChart.match(/\bNumber\(exactValue\)/g)).toHaveLength(1)
    expect(chartProjection).toContain(
      "Presentation-only conversion at the Recharts coordinate leaf boundary"
    )
    expect(chart).toContain("formatSnapshotAmount(point.exactValue, currency)")
    expect(historyChart).not.toMatch(
      /investedCzk|netDeposits|costBasis|realizedPnl|unrealizedPnl|currentValue|currentCzk|baseline/
    )
    expect(historyChart).not.toMatch(
      /\bMath\.|parseFloat|parseInt|\.toFixed\(|\.reduce\(|\.sort\(|\bFX\b/
    )
    expect(historyChart).not.toMatch(/\bCZK\b|Kč|Czk/)
  })

  it("keeps dashboard and current portfolio production independent from history", async () => {
    const dashboardFiles = [
      ...(await filesUnder("src/app/dashboard")),
      ...(await filesUnder("src/modules/dashboard")),
    ].filter((file) => /\.(?:ts|tsx)$/.test(file) && !/\.test\./.test(file))
    const dashboard = (await Promise.all(dashboardFiles.map((file) => source(file)))).join("\n")
    const page = await source("src/app/portfolio/page.tsx")

    expect(dashboard).not.toContain("/api/portfolio/history")
    expect(dashboard).not.toContain("PortfolioLineChart")
    expect(page).toContain("view.summary.totalValue")
    expect(page).toContain("<SnapshotHoldingsTable")
    expect(page).toContain("view.summary.cashByCurrency")
    expect(page).toContain("view.summary.netDepositsByCurrency")
    expect(page).not.toContain("latestHistoryPoint")
    expect(page).not.toMatch(/historyState.*(?:summary|positions|breakdown|accounts)/i)
  })
})

describe("R7 in-process browser and state acceptance", () => {
  it("runs one browser GET through NextAuth and one exact authenticated Python GET", async () => {
    const history = {
      range: "1Y" as const,
      currency: "EUR",
      points: [
        {
          timestamp: "2032-08-01T00:00:00.000",
          cashValue: "-10.000000",
          investmentValue: "100.123456",
          liabilitiesValue: "5.000000",
          netWorthValue: "85.123456",
        },
      ],
    }
    let internalToken = ""
    const pythonFetch = vi.fn<typeof fetch>(async (input, init) => {
      const request = new Request(input, init)
      expect(request.url).toBe(`${BACKEND_URL}/api/v1/portfolio/history?range=1Y`)
      expect(request.method).toBe("GET")
      expect(await request.text()).toBe("")
      expect(request.headers.get("Accept")).toBe("application/json")
      expect(request.headers.has("Cookie")).toBe(false)
      internalToken = request.headers.get("Authorization")?.slice("Bearer ".length) ?? ""
      expect(internalToken).not.toBe("")
      expect(internalToken).not.toBe("browser-authorization")
      const { payload } = await jwtVerify(internalToken, KEY, {
        algorithms: ["HS256"],
        issuer: "finance-app-next",
        audience: "finance-app-python",
      })
      expect(payload.sub).toBe("r7-audit-user")
      expect(payload.email).toBe("r7-audit@example.test")
      expect(payload.jti).toBeTruthy()
      return jsonResponse(history)
    })
    vi.stubGlobal("fetch", pythonFetch)
    const browserFetch = vi.fn<typeof fetch>(async (input, init) => {
      expect(input).toBe("/api/portfolio/history?range=1Y")
      expect(init).toEqual({ method: "GET", cache: "no-store" })
      expect(init?.headers).toBeUndefined()
      return portfolioHistoryGet(
        new NextRequest("http://next.test/api/portfolio/history?range=1Y", {
          method: "GET",
          headers: {
            Authorization: "browser-authorization",
            Cookie: "next-auth=session-cookie",
          },
        })
      )
    })

    const result = await requestPortfolioHistory("1Y", "EUR", browserFetch)

    expect(browserFetch).toHaveBeenCalledOnce()
    expect(pythonFetch).toHaveBeenCalledOnce()
    expect(getSession).toHaveBeenCalledOnce()
    expect(result).toEqual({ status: "ready", data: history })
    expect(JSON.stringify(result)).not.toContain(internalToken)
    expect(JSON.stringify(result)).not.toMatch(/userId|snapshotId|accountId|request_id/)
    if (result.status !== "ready") throw new Error("Expected ready history.")
    expect(buildPortfolioHistoryChartPoints(result.data.points, "netWorth")).toEqual([
      {
        timestamp: "2032-08-01T00:00:00.000",
        exactValue: "85.123456",
        displayValue: 85.123456,
        dateLabel: expect.any(String),
      },
    ])
  })

  it("ignores stale range completion and keeps account selection request-free", async () => {
    let resolveOneYear: ((response: Response) => void) | undefined
    let resolveOneMonth: ((response: Response) => void) | undefined
    const oneYearFetch = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>((resolve) => {
          resolveOneYear = resolve
        })
    )
    const oneMonthFetch = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>((resolve) => {
          resolveOneMonth = resolve
        })
    )
    const ranges: SnapshotPortfolioHistoryRange[] = []
    const cancelOneYear = startPortfolioHistoryRequest(
      "1Y",
      "EUR",
      (result) => {
        if (result.status !== "error") ranges.push(result.data.range)
      },
      oneYearFetch
    )
    cancelOneYear()
    startPortfolioHistoryRequest(
      "1M",
      "EUR",
      (result) => {
        if (result.status !== "error") ranges.push(result.data.range)
      },
      oneMonthFetch
    )
    resolveOneMonth?.(jsonResponse({ range: "1M", currency: "EUR", points: [] }))
    await vi.waitFor(() => expect(ranges).toEqual(["1M"]))
    resolveOneYear?.(jsonResponse({ range: "1Y", currency: "EUR", points: [] }))
    await Promise.resolve()
    await Promise.resolve()
    expect(ranges).toEqual(["1M"])

    const data = portfolioSnapshotFixture()
    const model = buildPortfolioPageModel(data)
    const selected = selectPortfolioAccountView(model, "account-b")
    expect(selected?.summary).toBe(data.accounts[1]?.summary)
    expect(selected?.positions[0]?.position).toBe(data.accounts[1]?.positions[0])
    expect(oneYearFetch).toHaveBeenCalledOnce()
    expect(oneMonthFetch).toHaveBeenCalledOnce()
  })
})
