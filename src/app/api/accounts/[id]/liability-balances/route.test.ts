import { getServerSession } from "next-auth"
import type { NextRequest } from "next/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { createManualLiabilityBalance } from "@/modules/accounts/server/liability-balance-api"
import { forwardedPythonError } from "@/modules/python-api/server/errors"
import * as route from "./route"

vi.mock("next-auth", () => ({ getServerSession: vi.fn() }))
vi.mock("@/lib/auth", () => ({ authOptions: { providers: [] } }))
vi.mock("@/modules/accounts/server/liability-balance-api", () => ({
  createManualLiabilityBalance: vi.fn(),
}))

const getSession = vi.mocked(getServerSession)
const create = vi.mocked(createManualLiabilityBalance)
const BODY = {
  effectiveAt: "2036-08-19T10:20:30.123",
  currency: "CZK",
  outstandingPrincipal: "100.000000",
  accruedInterest: "2.000000",
  feesOutstanding: "3.000000",
}
const RESPONSE = {
  balanceId: "balance-1",
  accountId: "path-account",
  effectiveAt: "2036-08-19T10:20:30.123",
  currency: "CZK",
  totalOutstanding: "105.000000",
  source: "manual" as const,
  status: "created" as const,
}

function request(body: unknown = BODY): NextRequest {
  return new Request("http://next.test/api/accounts/path-account/liability-balances", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }) as NextRequest
}

beforeEach(() => vi.clearAllMocks())

describe("manual liability balance Next route", () => {
  it("requires a verified session before it reaches Python", async () => {
    getSession.mockResolvedValue(null)

    const response = await route.POST(request(), {
      params: Promise.resolve({ id: "path-account" }),
    })

    expect(response.status).toBe(401)
    expect(response.headers.get("Cache-Control")).toBe("no-store")
    expect(create).not.toHaveBeenCalled()
  })

  it("forwards only the full allowlisted observation and route account identity", async () => {
    getSession.mockResolvedValue({
      user: { id: "user-1", email: "user@example.test" },
      expires: "2036-01-01",
    })
    create.mockResolvedValue(RESPONSE)

    const response = await route.POST(request(), {
      params: Promise.resolve({ id: "path-account" }),
    })

    expect(create).toHaveBeenCalledWith(
      { userId: "user-1", email: "user@example.test" },
      "path-account",
      BODY
    )
    expect(response.status).toBe(201)
    expect(response.headers.get("Cache-Control")).toBe("no-store")
    expect(await response.json()).toEqual(RESPONSE)
  })

  it("rejects missing or caller-controlled fields before Python", async () => {
    getSession.mockResolvedValue({
      user: { id: "user-1", email: "user@example.test" },
      expires: "2036-01-01",
    })

    const response = await route.POST(request({ ...BODY, source: "provider" }), {
      params: Promise.resolve({ id: "path-account" }),
    })

    expect(response.status).toBe(422)
    expect(await response.json()).toEqual({
      error: { code: "validation_error", message: "Request validation failed." },
    })
    expect(create).not.toHaveBeenCalled()
  })

  it("forwards only the safe Python error envelope", async () => {
    getSession.mockResolvedValue({
      user: { id: "user-1", email: "user@example.test" },
      expires: "2036-01-01",
    })
    create.mockRejectedValue(
      forwardedPythonError(409, "manual_liability_balance_conflict", "Conflict.")
    )

    const response = await route.POST(request(), {
      params: Promise.resolve({ id: "path-account" }),
    })

    expect(response.status).toBe(409)
    expect(await response.json()).toEqual({
      error: { code: "manual_liability_balance_conflict", message: "Conflict." },
    })
  })
})
