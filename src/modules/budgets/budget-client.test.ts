import { describe, expect, it, vi } from "vitest"

import { BUDGET_PATH, requestBudget, saveBudget } from "./budget-client"

const BUDGET = {
  id: "budget-1",
  month: 8,
  year: 2026,
  periodType: "monthly",
  currency: "CZK",
  rollover: false,
  accountIds: ["account-1"],
  totalLimit: "1000.000000",
  totalBaseLimit: "1000.000000",
  totalRollover: "0.000000",
  totalSpent: "250.000000",
  totalRemaining: "750.000000",
  progressPct: "25.0000",
  isOver: false,
  alerts: [],
  items: [],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("browser budget client", () => {
  it("loads an exact generated monthly budget without caching", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse(BUDGET))

    await expect(requestBudget(8, 2026, fetchMock)).resolves.toEqual(BUDGET)
    expect(fetchMock).toHaveBeenCalledWith(`${BUDGET_PATH}?month=8&year=2026`, {
      cache: "no-store",
    })
  })

  it("saves exact amount strings through PUT", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse(BUDGET))
    const payload = {
      month: 8,
      year: 2026,
      rollover: true,
      items: [{ categoryId: "food", amount: "123.456789", currency: "CZK" }],
    }

    await saveBudget(payload, fetchMock)

    expect(fetchMock).toHaveBeenCalledWith(BUDGET_PATH, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    })
  })
})
