import { describe, expect, it, vi } from "vitest"

import { requestCreateManualLiabilityBalance } from "./liability-balance-client"
import type { LiabilityBalanceClientError } from "./liability-balance-client"

const RESPONSE = {
  balanceId: "balance-1",
  accountId: "account-1",
  effectiveAt: "2036-08-19T10:20:30.123",
  currency: "CZK",
  totalOutstanding: "105.000000",
  source: "manual" as const,
  status: "created" as const,
}
const REQUEST = {
  effectiveAt: "2036-08-19T10:20:30.123",
  currency: "CZK",
  outstandingPrincipal: "100.000000",
  accruedInterest: "2.000000",
  feesOutstanding: "3.000000",
}

function jsonResponse(body: unknown, status = 201): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("browser liability balance client", () => {
  it("posts the complete explicit observation to its scoped Next route", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse(RESPONSE))

    await expect(
      requestCreateManualLiabilityBalance("account/1", REQUEST, fetchMock)
    ).resolves.toEqual(RESPONSE)

    expect(fetchMock).toHaveBeenCalledWith("/api/accounts/account%2F1/liability-balances", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(REQUEST),
      cache: "no-store",
    })
    expect(JSON.stringify(fetchMock.mock.calls[0])).not.toMatch(
      /source|externalId|createdAt|userId|membership|Bearer/
    )
  })

  it("keeps safe API failures and rejects unexpected success fields", async () => {
    const safeFailure = vi.fn<typeof fetch>(async () =>
      jsonResponse(
        { error: { code: "manual_liability_balance_conflict", message: "Conflict." } },
        409
      )
    )
    await expect(
      requestCreateManualLiabilityBalance("account-1", REQUEST, safeFailure)
    ).rejects.toEqual(
      expect.objectContaining<Partial<LiabilityBalanceClientError>>({
        status: 409,
        code: "manual_liability_balance_conflict",
        message: "Conflict.",
      })
    )

    const extraField = vi.fn<typeof fetch>(async () =>
      jsonResponse({ ...RESPONSE, createdAt: "must-not-leak" })
    )
    await expect(
      requestCreateManualLiabilityBalance("account-1", REQUEST, extraField)
    ).rejects.toEqual(
      expect.objectContaining<Partial<LiabilityBalanceClientError>>({
        status: 502,
        code: "python_api_contract_error",
      })
    )
  })
})
