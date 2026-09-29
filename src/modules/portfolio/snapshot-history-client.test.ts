import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it, vi } from "vitest"

import { requestPortfolioHistory, startPortfolioHistoryRequest } from "./snapshot-history-client"
import type { SnapshotPortfolioHistoryRange } from "./snapshot-history-contract"

const POINT = {
  timestamp: "2036-01-01T00:00:00.000",
  resolutionMinutes: 1440,
  cashValue: "10.000000",
  investmentValue: "20.000000",
  liabilitiesValue: "5.000000",
  netWorthValue: "25.000000",
}

function history(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    range: "1Y",
    state: "ready",
    currency: "EUR",
    generationId: "generation-1",
    publicationVersion: 1,
    coveredThrough: "2036-01-01T23:59:00.000",
    preferredResolutionMinutes: 1440,
    resolutions: [1440],
    coverage: [
      {
        resolutionMinutes: 1440,
        start: "2036-01-01T00:00:00.000",
        end: "2036-01-02T00:00:00.000",
      },
    ],
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

  it("preserves the native multi-currency snapshot breakdown", async () => {
    const point = {
      ...POINT,
      cashByCurrency: [
        { currency: "CZK", value: "100.000000" },
        { currency: "EUR", value: "20.000000" },
      ],
      investmentByCurrency: [{ currency: "USD", value: "30.000000" }],
      liabilitiesByCurrency: [],
      netInvestedByCurrency: [
        { currency: "EUR", value: "10.000000" },
        { currency: "USD", value: "15.000000" },
      ],
    }
    const payload = history({ points: [point] })

    await expect(
      requestPortfolioHistory("1Y", "EUR", vi.fn(async () => jsonResponse(payload)))
    ).resolves.toEqual({ status: "ready", data: payload })
  })

  it("accepts exact native precision and mixed minute, hour, and arbitrary coverage", async () => {
    const points = [
      { ...POINT, timestamp: "2036-01-01T00:00:00.000", resolutionMinutes: 1,
        cashByCurrency: [{ currency: "EUR", value: "0.123456789123" }] },
      { ...POINT, timestamp: "2036-01-01T01:00:00.000", resolutionMinutes: 60 },
      { ...POINT, timestamp: "2036-01-01T01:30:00.000", resolutionMinutes: 30 },
    ]
    const payload = history({
      coveredThrough: "2036-01-01T01:30:00.000",
      preferredResolutionMinutes: 30,
      resolutions: [1, 30, 60],
      coverage: [
        { resolutionMinutes: 1, start: points[0].timestamp, end: points[1].timestamp },
        { resolutionMinutes: 60, start: points[1].timestamp, end: points[2].timestamp },
        { resolutionMinutes: 30, start: points[2].timestamp, end: "2036-01-01T01:30:00.001" },
      ],
      points,
    })

    await expect(requestPortfolioHistory("1Y", "EUR", vi.fn(async () => jsonResponse(payload))))
      .resolves.toEqual({ status: "ready", data: payload })
  })

  it("includes the selected account while leaving aggregate requests unchanged", async () => {
    const payload = history()
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse(payload))

    await requestPortfolioHistory("1Y", "EUR", fetchImplementation, "account-b")

    expect(fetchImplementation).toHaveBeenCalledWith(
      "/api/portfolio/history?range=1Y&accountId=account-b",
      { method: "GET", cache: "no-store" }
    )
    await requestPortfolioHistory("1Y", "EUR", fetchImplementation, null)
    expect(fetchImplementation).toHaveBeenLastCalledWith("/api/portfolio/history?range=1Y", {
      method: "GET",
      cache: "no-store",
    })
  })

  it("maps an exact empty response only to empty", async () => {
    const payload = {
      range: "1Y",
      state: "empty",
      currency: "EUR",
      resolutions: [],
      coverage: [],
      points: [],
    }

    await expect(
      requestPortfolioHistory(
        "1Y",
        "EUR",
        vi.fn(async () => jsonResponse(payload))
      )
    ).resolves.toEqual({ status: "empty", data: payload })
  })

  it.each(["1D", "1W", "1M", "3M", "6M", "1Y", "5Y", "10Y", "ALL"] as const)(
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
    ["more than 480 points", history({ points: Array.from({ length: 481 }, () => POINT) })],
    ["duplicate resolutions", history({ resolutions: [1440, 1440] })],
    ["unused advertised resolution", history({ resolutions: [1440, 720] })],
    ["nonpositive preferred resolution", history({ preferredResolutionMinutes: 0 })],
    ["ready without points", history({ points: [] })],
    ["empty with points", history({ state: "empty" })],
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
        resolutionMinutes: POINT.resolutionMinutes,
        cashValue: POINT.cashValue,
        investmentValue: POINT.investmentValue,
        netWorthValue: POINT.netWorthValue,
      },
    ],
    ["JSON number", { ...POINT, cashValue: 10 }],
    ["non-integer resolution", { ...POINT, resolutionMinutes: 1.5 }],
    ["nonpositive resolution", { ...POINT, resolutionMinutes: 0 }],
    ["unannounced resolution", { ...POINT, resolutionMinutes: 720 }],
    ["negative investment", { ...POINT, investmentValue: "-1.000000" }],
    ["negative liabilities", { ...POINT, liabilitiesValue: "-1.000000" }],
    ["exponent", { ...POINT, investmentValue: "1e2" }],
    ["missing scale", { ...POINT, liabilitiesValue: "5.0" }],
    ["NaN", { ...POINT, netWorthValue: "NaN" }],
    ["Infinity", { ...POINT, netWorthValue: "Infinity" }],
    ["leading plus", { ...POINT, cashValue: "+10.000000" }],
    ["leading zero", { ...POINT, cashValue: "010.000000" }],
    ["overflow", { ...POINT, cashValue: "1000000000000.000000" }],
    [
      "duplicate native currency",
      {
        ...POINT,
        cashByCurrency: [
          { currency: "EUR", value: "1.000000" },
          { currency: "EUR", value: "2.000000" },
        ],
      },
    ],
    [
      "invalid native currency amount",
      { ...POINT, investmentByCurrency: [{ currency: "usd", value: "1" }] },
    ],
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

  it("preserves a rebuilding mixed-resolution response without merging points", async () => {
    const mixed = history({
      state: "rebuilding",
      preferredResolutionMinutes: 720,
      resolutions: [1440, 720],
      coverage: [
        {
          resolutionMinutes: 1440,
          start: "2036-01-01T00:00:00.000",
          end: "2036-01-02T00:00:00.000",
        },
        {
          resolutionMinutes: 720,
          start: "2036-01-02T00:00:00.000",
          end: "2036-01-03T00:00:00.000",
        },
      ],
      coveredThrough: "2036-01-02T12:00:00.000",
      points: [
        POINT,
        {
          ...POINT,
          timestamp: "2036-01-02T12:00:00.000",
          resolutionMinutes: 720,
        },
      ],
    })

    await expect(
      requestPortfolioHistory(
        "1Y",
        "EUR",
        vi.fn(async () => jsonResponse(mixed))
      )
    ).resolves.toEqual({ status: "rebuilding", data: mixed })
  })

  it("accepts truthful coarser-only coverage than the preferred range resolution", async () => {
    const coarser = history({ preferredResolutionMinutes: 720 })

    await expect(
      requestPortfolioHistory(
        "1Y",
        "EUR",
        vi.fn(async () => jsonResponse(coarser))
      )
    ).resolves.toEqual({ status: "ready", data: coarser })
  })

  it("assigns a seam point to the next half-open coverage segment and accepts final through", async () => {
    const seam = history({
      preferredResolutionMinutes: 720,
      resolutions: [1440, 720],
      coverage: [
        {
          resolutionMinutes: 1440,
          start: "2036-01-01T00:00:00.000",
          end: "2036-01-02T00:00:00.000",
        },
        {
          resolutionMinutes: 720,
          start: "2036-01-02T00:00:00.000",
          end: "2036-01-02T12:00:00.000",
        },
      ],
      coveredThrough: "2036-01-02T00:00:00.000",
      points: [
        { ...POINT, timestamp: "2036-01-01T23:59:00.000" },
        {
          ...POINT,
          timestamp: "2036-01-02T00:00:00.000",
          resolutionMinutes: 720,
        },
      ],
    })

    await expect(
      requestPortfolioHistory(
        "1Y",
        "EUR",
        vi.fn(async () => jsonResponse(seam))
      )
    ).resolves.toEqual({ status: "ready", data: seam })
  })

  it("preserves a terminal failed state without inventing fallback points", async () => {
    const failed = {
      range: "1Y",
      state: "failed",
      currency: "EUR",
      resolutions: [],
      coverage: [],
      points: [],
    }

    await expect(
      requestPortfolioHistory(
        "1Y",
        "EUR",
        vi.fn(async () => jsonResponse(failed))
      )
    ).resolves.toEqual({ status: "failed", data: failed })
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
    expect(source).not.toMatch(/userId|currency.*query|retry|fallback/)
  })
})
