import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it, vi } from "vitest"

import {
  PORTFOLIO_WORKFLOW_PATH,
  requestPortfolioPageState,
} from "@/modules/portfolio/snapshot-page-client"
import { startPortfolioHistoryRequest } from "@/modules/portfolio/snapshot-history-client"
import {
  buildPortfolioPageModel,
  selectPortfolioAccountView,
} from "@/modules/portfolio/snapshot-page-model"
import { portfolioSnapshotFixture } from "@/test/portfolio-snapshot-fixture"

const REFRESH = {
  netWorthSnapshotId: "net-worth-snapshot",
  netWorthStatus: "created" as const,
  timestamp: "2032-08-02T00:00:00.000",
  granularity: "day",
  currency: "EUR",
  calculationVersion: 7,
  refreshAccountCount: 2,
  reuseOnlyAccountCount: 0,
  createdAccountSnapshotCount: 2,
  replayedAccountSnapshotCount: 0,
  reusedAccountSnapshotCount: 0,
  selectedAccountSnapshotCount: 2,
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("portfolio page snapshot workflow", () => {
  it("uses one bodyless no-store POST for initial current data", async () => {
    const fetchMock = vi.fn(async (_input: string | URL | Request, _init?: RequestInit) =>
      jsonResponse({
        status: "ready",
        refresh: REFRESH,
        data: portfolioSnapshotFixture(),
      })
    )

    const state = await requestPortfolioPageState(fetchMock)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith(PORTFOLIO_WORKFLOW_PATH, {
      method: "POST",
      cache: "no-store",
    })
    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe("/api/snapshot-workflow/portfolio")
    expect(url).not.toContain("?")
    expect(init).not.toHaveProperty("body")
    expect(init).not.toHaveProperty("headers")
    expect(state.status).toBe("ready")
    if (state.status === "ready") {
      expect(state.data.summary.totalValue).toBe("777.123456")
      expect(state.data.summary.cashByCurrency[2]).toEqual({
        currency: "USD",
        amount: "-50.000000",
      })
      expect(state.data.summary.netDepositsByCurrency[1]).toEqual({
        currency: "EUR",
        amount: "500.000000",
      })
      expect(state.data.accounts[0]?.positions[0]?.value).toBe("123.456789")
    }
  })

  it("returns the explicit empty state and makes no follow-up request", async () => {
    const emptyRefresh = {
      ...REFRESH,
      refreshAccountCount: 0,
      createdAccountSnapshotCount: 0,
      selectedAccountSnapshotCount: 0,
    }
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        status: "empty",
        refresh: emptyRefresh,
      })
    )

    await expect(requestPortfolioPageState(fetchMock)).resolves.toEqual({
      status: "empty",
      refresh: emptyRefresh,
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it.each([
    [401, "authentication_required", "Authentication is required."],
    [503, "python_api_configuration_error", "The Python API adapter is not configured."],
    [502, "python_api_contract_error", "The Python API returned an incompatible response."],
  ])("shows the safe %i error envelope", async (status, code, message) => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(
        {
          error: {
            code,
            message,
            request_id: "must-not-be-rendered",
          },
        },
        status
      )
    )

    await expect(requestPortfolioPageState(fetchMock)).resolves.toEqual({
      status: "error",
      code,
      message,
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("does not expose raw backend errors or retry a failed request", async () => {
    const rawSecret = "raw-token-and-traceback"
    const fetchMock = vi.fn(async () =>
      jsonResponse({ detail: rawSecret, traceback: rawSecret }, 502)
    )

    const state = await requestPortfolioPageState(fetchMock)

    expect(state).toEqual({
      status: "error",
      code: "python_api_unavailable",
      message: "Portfolio se nepodařilo načíst.",
    })
    expect(JSON.stringify(state)).not.toContain(rawSecret)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("maps malformed success and non-JSON/network failures to safe errors without retry", async () => {
    const malformed = vi.fn(async () => jsonResponse({ status: "ready", raw: "secret" }))
    const unavailable = vi.fn(async () => {
      throw new Error("Bearer secret-token")
    })

    await expect(requestPortfolioPageState(malformed)).resolves.toEqual({
      status: "error",
      code: "python_api_contract_error",
      message: "Portfolio API vrátilo nekompatibilní odpověď.",
    })
    await expect(requestPortfolioPageState(unavailable)).resolves.toEqual({
      status: "error",
      code: "python_api_unavailable",
      message: "Portfolio se nepodařilo načíst.",
    })
    expect(malformed).toHaveBeenCalledTimes(1)
    expect(unavailable).toHaveBeenCalledTimes(1)
  })

  it("refresh calls the same workflow once per explicit action and no legacy endpoint", async () => {
    const fetchMock = vi.fn(async (_input: string | URL | Request, _init?: RequestInit) =>
      jsonResponse({
        status: "ready",
        refresh: REFRESH,
        data: portfolioSnapshotFixture(),
      })
    )

    await requestPortfolioPageState(fetchMock)
    await requestPortfolioPageState(fetchMock)

    expect(fetchMock).toHaveBeenCalledTimes(2)
    for (const [url, init] of fetchMock.mock.calls) {
      expect(url).toBe("/api/snapshot-workflow/portfolio")
      expect(init).toEqual({ method: "POST", cache: "no-store" })
    }
    expect(fetchMock.mock.calls.flat().join(" ")).not.toMatch(
      /\/api\/rates|snapshots\/recalculate|\/api\/portfolio(?:\?|$)/
    )
  })

  it("account selection is local and uses the loaded server account view", () => {
    const fetchMock = vi.fn()
    const data = portfolioSnapshotFixture()
    const model = buildPortfolioPageModel(data)

    const selected = selectPortfolioAccountView(model, "account-b")

    expect(fetchMock).not.toHaveBeenCalled()
    expect(selected?.summary).toBe(data.accounts[1]?.summary)
    expect(selected?.summary.cashByCurrency).toBe(data.accounts[1]?.summary.cashByCurrency)
    expect(selected?.summary.netDepositsByCurrency).toBe(
      data.accounts[1]?.summary.netDepositsByCurrency
    )
    expect(selected?.positions[0]?.position).toBe(data.accounts[1]?.positions[0])
  })

  it("cancels an obsolete history request without changing current portfolio data", async () => {
    let resolveHistory: ((response: Response) => void) | undefined
    const historyFetch = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>((resolve) => {
          resolveHistory = resolve
        })
    )
    const current = portfolioSnapshotFixture()
    const results: unknown[] = []

    const cancel = startPortfolioHistoryRequest(
      "1Y",
      current.currency,
      (result) => {
        results.push(result)
      },
      historyFetch
    )
    cancel()
    resolveHistory?.(
      jsonResponse({
        range: "1Y",
        currency: current.currency,
        points: [],
      })
    )
    await Promise.resolve()
    await Promise.resolve()

    expect(results).toEqual([])
    expect(current.summary.totalValue).toBe("777.123456")
    expect(current.accounts[0]?.positions[0]?.value).toBe("123.456789")
  })

  it("guards the mount request and does not render a manifest or raw error fields", async () => {
    const page = await readFile(path.join(process.cwd(), "src/app/portfolio/page.tsx"), "utf8")

    expect(page).toContain("initialLoadStarted.current")
    expect(page).toContain("void loadPortfolio()")
    expect(page).toContain("requestPortfolioPageState()")
    expect(page).toContain('state.status === "ready" ? state.data.currency : null')
    expect(page).toContain('state.status === "ready" ? state.refresh.netWorthSnapshotId : null')
    expect(page).toContain("startPortfolioHistoryRequest(historyRange, historyCurrency")
    expect(page).toContain("[historyCurrency, historyRange, historySnapshotId]")
    expect(page).toContain('historyState.status === "loading"')
    expect(page).toContain('historyState.status === "empty"')
    expect(page).toContain('historyState.status === "error"')
    expect(page).toContain('historyState.status === "ready"')
    expect(page).toContain("Historie celého portfolia")
    expect(page).toContain("Načítám historii portfolia…")
    expect(page).toContain("historyState.data.points")
    expect(page).toContain("historyState.data.currency")
    expect(page).toContain("view.summary.totalValue")
    expect(page).toContain("view.summary.netDepositsValue")
    expect(page).toContain("view.summary.cashByCurrency")
    expect(page).toContain("view.summary.netDepositsByCurrency")
    expect(page).toContain("SnapshotCurrencyBreakdown")
    expect(page).toContain("Hotovost podle měny")
    expect(page).toContain("Čisté vklady podle měny")
    expect(page).toContain("<SnapshotHoldingsTable")
    expect(page).toContain('state.status === "empty"')
    expect(page).toContain('state.status === "error"')
    expect(page).toContain("{state.message}")
    expect(page).not.toMatch(/\b(?:snapshotId|manifest|request_id|traceback|raw body)\b/i)
    expect(page).not.toContain("state.code")
    expect(page).not.toContain("currentValueCzk")
    expect(page).not.toContain("latestHistoryPoint")
  })
})
