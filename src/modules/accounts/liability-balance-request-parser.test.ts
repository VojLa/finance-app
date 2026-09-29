import { describe, expect, it } from "vitest"

import { parseCreateManualLiabilityBalanceRequest } from "./liability-balance-request-parser"

const REQUEST = {
  effectiveAt: "2036-08-19T10:20:30.123",
  currency: "CZK",
  outstandingPrincipal: "100.000000",
  accruedInterest: "2.000000",
  feesOutstanding: "3.000000",
}

describe("manual liability balance request parser", () => {
  it("copies every explicit user-entered observation field", () => {
    const parsed = parseCreateManualLiabilityBalanceRequest(REQUEST)

    expect(parsed).toEqual(REQUEST)
    expect(parsed).not.toBe(REQUEST)
  })

  it.each([
    "source",
    "externalId",
    "external_id",
    "createdAt",
    "created_at",
    "accountId",
    "userId",
    "role",
  ])("rejects caller-controlled field %s", (field) => {
    expect(() =>
      parseCreateManualLiabilityBalanceRequest({ ...REQUEST, [field]: "caller-controlled" })
    ).toThrow(TypeError)
  })

  it.each([
    "effectiveAt",
    "currency",
    "outstandingPrincipal",
    "accruedInterest",
    "feesOutstanding",
  ])("requires %s rather than defaulting it", (field) => {
    const request = { ...REQUEST }
    delete request[field as keyof typeof request]
    expect(() => parseCreateManualLiabilityBalanceRequest(request)).toThrow(TypeError)
  })

  it("requires transport strings so Python owns exact money validation", () => {
    expect(() =>
      parseCreateManualLiabilityBalanceRequest({ ...REQUEST, outstandingPrincipal: 100 })
    ).toThrow(TypeError)
  })
})
