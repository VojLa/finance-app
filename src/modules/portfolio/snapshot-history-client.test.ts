import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it, vi } from "vitest"

import { requestPortfolioHistory, startPortfolioHistoryRequest } from "./snapshot-history-client"
import type { SnapshotPortfolioHistoryRange } from "./snapshot-history-contract"

const POINT = {
  timestamp: "2036-01-01T00:00:00.000",
  cashValue: "10.000000",
  investmentValue: "20.000000",
  liabilitiesValue: "5.000000",
  netWorthValue: "25.000000",
}

function history(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    range: "1Y",
    currency: "EUR",
    points: [POINT],
    ...overrides,
  }
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("snapshot portfolio history browser client", () => {
  it("returns exact valid data with a bodyless no-store GET", async () => {
    const payload = history()
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse(payload))

    const result = await requestPortfolioHistory("1Y", "EUR", fetchImplementation)

    expect(result).toEqual({ status: "ready", data: payload })
    expect(fetchImplementation).toHaveBeenCalledOnce()
    expect(fetchImplementation).toHaveBeenCalledWith("/api/portfolio/history?range=1Y", {
      method: "GET",
      cache: "no-store",
    })
    const init = fetchImplementation.mock.calls[0]?.[1]
    expect(init).not.toHaveProperty("body")
    expect(init).not.toHaveProperty("headers")
  })

  it("maps an exact empty response only to empty", async () => {
    const payload = history({ points: [] })

    await expect(
      requestPortfolioHistory(
        "1Y",
        "EUR",
        vi.fn(async () => jsonResponse(payload))
      )
    ).resolves.toEqual({ status: "empty", data: payload })
  })

  it.each(["1W", "1M", "3M", "6M", "1Y", "ALL"] as const)(
    "accepts and preserves the exact %s range",
    async (range) => {
      const payload = history({ range })
      const fetchImplementation = vi.fn(async () => jsonResponse(payload))

      const result = await requestPortfolioHistory(range, "EUR", fetchImplementation)

      expect(result).toEqual({ status: "ready", data: payload })
      expect(fetchImplementation).toHaveBeenCalledWith(`/api/portfolio/history?range=${range}`, {
        method: "GET",
        cache: "no-store",
      })
    }
  )

  it.each([
    ["response range mismatch", history({ range: "1M" })],
    ["response currency mismatch", history({ currency: "USD" })],
    ["lowercase currency", history({ currency: "eur" })],
    ["extra top-level field", history({ extra: "forbidden" })],
    [
      "missing top-level field",
      {
        range: "1Y",
        currency: "EUR",
      },
    ],
    ["points is not an array", history({ points: {} })],
    ["more than 512 points", history({ points: Array.from({ length: 513 }, () => POINT) })],
  ])("fails closed for %s", async (_name, payload) => {
    await expect(
      requestPortfolioHistory(
        "1Y",
        "EUR",
        vi.fn(async () => jsonResponse(payload))
      )
    ).resolves.toEqual({
      status: "error",
      message: "Historii portfolia se nepodařilo načíst.",
    })
  })

  it.each([
    ["extra point field", { ...POINT, extra: "forbidden" }],
    [
      "missing point field",
      {
        timestamp: POINT.timestamp,
        cashValue: POINT.cashValue,
        investmentValue: POINT.investmentValue,
        netWorthValue: POINT.netWorthValue,
      },
    ],
    ["JSON number", { ...POINT, cashValue: 10 }],
    ["exponent", { ...POINT, investmentValue: "1e2" }],
    ["missing scale", { ...POINT, liabilitiesValue: "5.0" }],
    ["NaN", { ...POINT, netWorthValue: "NaN" }],
    ["Infinity", { ...POINT, netWorthValue: "Infinity" }],
    ["leading plus", { ...POINT, cashValue: "+10.000000" }],
    ["leading zero", { ...POINT, cashValue: "010.000000" }],
    ["overflow", { ...POINT, cashValue: "1000000000000.000000" }],
  ])("rejects point with %s", async (_name, point) => {
    await expect(
      requestPortfolioHistory(
        "1Y",
        "EUR",
        vi.fn(async () => jsonResponse(history({ points: [point] })))
      )
    ).resolves.toMatchObject({ status: "error" })
  })

  it.each([
    "2036-02-30T00:00:00.000",
    "2036-01-01T00:00:00",
    "2036-01-01T00:00:00.000Z",
    "not-a-date",
  ])("rejects invalid timestamp %s", async (timestamp) => {
    await expect(
      requestPortfolioHistory(
        "1Y",
        "EUR",
        vi.fn(async () => jsonResponse(history({ points: [{ ...POINT, timestamp }] })))
      )
    ).resolves.toMatchObject({ status: "error" })
  })

  it.each([
    ["duplicate", [POINT, { ...POINT }]],
    ["descending", [{ ...POINT, timestamp: "2036-01-02T00:00:00.000" }, POINT]],
  ])("rejects %s timestamps", async (_name, points) => {
    await expect(
      requestPortfolioHistory(
        "1Y",
        "EUR",
        vi.fn(async () => jsonResponse(history({ points })))
      )
    ).resolves.toMatchObject({ status: "error" })
  })

  it.each([
    ["network", vi.fn(async () => Promise.reject(new Error("secret traceback")))],
    [
      "non-JSON",
      vi.fn(
        async () =>
          new Response("raw secret", {
            status: 200,
            headers: { "Content-Type": "text/plain" },
          })
      ),
    ],
    [
      "backend safe error",
      vi.fn(async () =>
        jsonResponse(
          {
            error: {
              code: "portfolio_history_unavailable",
              message: "Portfolio history is unavailable.",
            },
          },
          409
        )
      ),
    ],
  ])("maps %s to error rather than empty without retry", async (_name, fetchImplementation) => {
    const result = await requestPortfolioHistory("1Y", "EUR", fetchImplementation)

    expect(result).toEqual({
      status: "error",
      message: "Historii portfolia se nepodařilo načíst.",
    })
    expect(fetchImplementation).toHaveBeenCalledOnce()
    expect(JSON.stringify(result)).not.toMatch(/secret|traceback|portfolio_history_unavailable/)
  })

  it("cancels a stale request before it can overwrite the latest range", async () => {
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
    const results: SnapshotPortfolioHistoryRange[] = []

    const cancelOneYear = startPortfolioHistoryRequest(
      "1Y",
      "EUR",
      (result) => {
        if (result.status !== "error") results.push(result.data.range)
      },
      oneYearFetch
    )
    cancelOneYear()
    startPortfolioHistoryRequest(
      "1M",
      "EUR",
      (result) => {
        if (result.status !== "error") results.push(result.data.range)
      },
      oneMonthFetch
    )
    resolveOneMonth?.(jsonResponse(history({ range: "1M" })))
    await vi.waitFor(() => expect(results).toEqual(["1M"]))
    resolveOneYear?.(jsonResponse(history({ range: "1Y" })))
    await Promise.resolve()
    await Promise.resolve()

    expect(results).toEqual(["1M"])
  })

  it("contains no raw response cast or financial number conversion", async () => {
    const source = await readFile(
      path.join(process.cwd(), "src/modules/portfolio/snapshot-history-client.ts"),
      "utf8"
    )

    expect(source).toContain("parseSnapshotPortfolioHistory")
    expect(source).not.toMatch(/\bas\s+Portfolio/)
    expect(source).not.toMatch(/\bNumber\s*\(|parseFloat|parseInt|toFixed/)
    expect(source).not.toMatch(/accountId|userId|currency.*query|retry|fallback/)
  })
})
