import { describe, expect, it, vi } from "vitest"

import {
  createTransaction,
  requestTransactions,
  TRANSACTIONS_PATH,
  updateTransaction,
} from "./transaction-client"

const TRANSACTION = {
  id: "transaction-1",
  date: "2026-08-09T00:00:00",
  amount: "-123.456789",
  currency: "CZK",
  type: "expense" as const,
  description: "Food",
  counterparty: null,
  note: null,
  accountId: "account-1",
  categoryId: null,
  category: null,
  account: { name: "Bank", currency: "CZK" },
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("browser transaction client", () => {
  it("lists through the same-origin route with encoded filters and no cache", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse({ transactions: [TRANSACTION], total: 1, page: 2, pages: 3 })
    )

    const result = await requestTransactions(
      { page: 2, type: "expense", categoryId: "food/sub", q: "tea & coffee" },
      fetchMock
    )

    expect(result.transactions[0].amount).toBe("-123.456789")
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain(`${TRANSACTIONS_PATH}?page=2`)
    expect(String(url)).toContain("categoryId=food%2Fsub")
    expect(String(url)).toContain("q=tea+%26+coffee")
    expect(init).toEqual({ cache: "no-store" })
  })

  it("posts the exact amount string and idempotency key unchanged", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse(TRANSACTION, 201))
    const payload = {
      date: "2026-08-09",
      amount: "123.456789",
      currency: "CZK",
      type: "expense" as const,
      accountId: "account-1",
      idempotencyKey: "command-1",
    }

    await createTransaction(payload, fetchMock)

    expect(fetchMock).toHaveBeenCalledWith(TRANSACTIONS_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    })
  })

  it("allowlists update fields through the typed payload", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse(TRANSACTION))

    await updateTransaction(
      "transaction-1",
      { amount: "99.000001", categoryId: null, idempotencyKey: "command-2" },
      fetchMock
    )

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      id: "transaction-1",
      amount: "99.000001",
      categoryId: null,
      idempotencyKey: "command-2",
    })
  })

  it("surfaces only the safe same-origin error string", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse({ error: "Zkontrolujte údaje transakce", traceback: "hidden" }, 422)
    )

    await expect(requestTransactions({ page: 1 }, fetchMock)).rejects.toThrow(
      "Zkontrolujte údaje transakce"
    )
  })
})
