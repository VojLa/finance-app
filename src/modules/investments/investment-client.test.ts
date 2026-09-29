import { describe, expect, it, vi } from "vitest"

import { createManualInvestment, requestSymbolDetail } from "./investment-client"

describe("investment client", () => {
  it("preserves exact decimal strings in a manual command", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json({
        eventId: "event-1",
        replayed: false,
        holdings: { created: 1, updated: 0, deleted: 0, total: 1, replayed: false },
        snapshot: { status: "ready", netWorthSnapshotId: "snapshot-1", timestamp: null },
      })
    )

    await createManualInvestment(
      {
        accountId: "account-1",
        idempotencyKey: "request-1",
        date: "2026-08-10",
        type: "buy",
        symbol: "VWCE",
        assetType: "etf",
        quantity: "1.2345678901",
        pricePerUnit: "100.0000000000",
        priceCurrency: "EUR",
        totalAmount: "123.4567890100",
        totalCurrency: "EUR",
      },
      fetcher as typeof fetch
    )

    const request = fetcher.mock.calls[0]
    expect(request[0]).toBe("/api/portfolio/transactions")
    expect(JSON.parse(String(request[1]?.body))).toMatchObject({
      idempotencyKey: "request-1",
      quantity: "1.2345678901",
      totalAmount: "123.4567890100",
    })
  })

  it("returns the generated exact symbol-detail contract", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json({
        symbol: "VWCE",
        positions: [
          {
            id: "holding-1",
            accountId: "account-1",
            accountName: "Broker",
            assetId: "asset-1",
            listingId: "listing-1",
            symbol: "VWCE",
            name: "VWCE",
            assetType: "etf",
            quantity: "2.0000000000",
            avgBuyPrice: "100.0000000000",
            currency: "EUR",
            currentPrice: null,
            currentValue: null,
            unrealizedPnl: null,
            realizedPnl: null,
            calculatedAt: "2026-08-10T12:00:00.000",
          },
        ],
        events: [],
      })
    )

    const result = await requestSymbolDetail("VWCE", fetcher as typeof fetch)

    expect(fetcher).toHaveBeenCalledWith("/api/portfolio/transactions?symbol=VWCE", {
      cache: "no-store",
    })
    expect(result.positions[0].quantity).toBe("2.0000000000")
  })
})
