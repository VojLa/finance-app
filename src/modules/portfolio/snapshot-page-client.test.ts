import { describe, expect, it, vi } from "vitest"

import {
  PORTFOLIO_REFRESH_WORKFLOW_PATH,
  PORTFOLIO_WORKFLOW_PATH,
  requestPortfolioPageState,
} from "./snapshot-page-client"

describe("portfolio snapshot page client", () => {
  it("uses the refresh workflow only for an explicit refresh", async () => {
    const fetchImplementation = vi.fn(async () =>
      new Response(
        JSON.stringify({
          status: "ready",
          current: {
            asOf: "2036-01-02T03:04:00.000Z",
            baselineTimestamp: "2036-01-02T03:04:00.000Z",
            historyAnchorSnapshotId: "net-worth-1",
            currency: "EUR",
            calculationVersion: 1,
          },
          data: {
            asOf: "2036-01-02T03:04:00.000Z",
            currency: "EUR",
            calculationVersion: 1,
            summary: {},
            accounts: [{}],
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    ) as typeof fetch

    await requestPortfolioPageState(fetchImplementation)
    await requestPortfolioPageState(fetchImplementation, true)

    expect(fetchImplementation).toHaveBeenNthCalledWith(
      1,
      PORTFOLIO_WORKFLOW_PATH,
      expect.objectContaining({ method: "POST", cache: "no-store" })
    )
    expect(fetchImplementation).toHaveBeenNthCalledWith(
      2,
      PORTFOLIO_REFRESH_WORKFLOW_PATH,
      expect.objectContaining({ method: "POST", cache: "no-store" })
    )
  })
})
