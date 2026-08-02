import { describe, expect, it, vi } from "vitest"

import {
  ACCOUNTS_PATH,
  requestAccounts,
  requestArchiveAccount,
  requestCreateAccount,
  requestUpdateAccount,
} from "./account-client"

const ACCOUNT = {
  id: "account-1",
  name: "Broker",
  type: "broker" as const,
  currency: "EUR",
  color: null,
  notes: null,
  role: "owner" as const,
  relation_type: "owner" as const,
  is_archived: false,
  created_at: "2036-01-01T00:00:00",
  updated_at: "2036-01-01T00:00:00",
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("browser account client", () => {
  it("lists through the relative no-store Next route", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse([ACCOUNT]))

    await expect(requestAccounts(fetchMock)).resolves.toEqual([ACCOUNT])

    expect(fetchMock).toHaveBeenCalledWith(ACCOUNTS_PATH, {
      method: "GET",
      cache: "no-store",
    })
  })

  it("creates with only generated user-editable fields", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse(ACCOUNT, 201))
    const payload = {
      name: "Broker",
      type: "broker" as const,
      currency: "EUR",
      color: null,
      notes: null,
    }

    await requestCreateAccount(payload, fetchMock)

    expect(fetchMock).toHaveBeenCalledWith(ACCOUNTS_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    })
    expect(JSON.stringify(fetchMock.mock.calls[0])).not.toMatch(
      /userId|user_id|membership|relationType|owner|backendUrl|Bearer/
    )
  })

  it("updates through a path parameter without type or identity", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse(ACCOUNT))

    await requestUpdateAccount("account/one", { name: "Updated", currency: "USD" }, fetchMock)

    expect(fetchMock).toHaveBeenCalledWith("/api/accounts/account%2Fone", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "Updated", currency: "USD" }),
      cache: "no-store",
    })
    expect(JSON.stringify(fetchMock.mock.calls[0])).not.toMatch(/type|userId|user_id|sub/)
  })

  it("archives with a bodyless POST and never deletes", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse({ ...ACCOUNT, is_archived: true })
    )

    await requestArchiveAccount("account-1", fetchMock)

    expect(fetchMock).toHaveBeenCalledWith("/api/accounts/account-1/archive", {
      method: "POST",
      cache: "no-store",
    })
    expect(JSON.stringify(fetchMock.mock.calls[0])).not.toContain("DELETE")
  })

  it.each([
    [401, "authentication_required", "Authentication is required."],
    [422, "validation_error", "Request validation failed."],
    [404, "account_not_found", "Account was not found."],
    [409, "account_archived", "Account is archived."],
    [502, "python_api_unavailable", "The Python API is unavailable."],
  ])("keeps the safe %s Next error contract", async (status, code, message) => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse({ error: { code, message, request_id: "hidden" } }, status)
    )

    const result = requestAccounts(fetchMock)

    await expect(result).rejects.toEqual(expect.objectContaining({ status, code, message }))
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("maps malformed, non-JSON and network responses without raw leakage or retry", async () => {
    const cases = [
      vi.fn<typeof fetch>(async () => jsonResponse({ token: "secret" })),
      vi.fn<typeof fetch>(
        async () =>
          new Response("secret traceback", {
            status: 500,
            headers: { "Content-Type": "text/plain" },
          })
      ),
      vi.fn<typeof fetch>(async () => {
        throw new Error("Bearer secret-token")
      }),
    ]

    for (const fetchMock of cases) {
      const result = requestAccounts(fetchMock)
      await expect(result).rejects.toMatchObject({
        status: 502,
        code: expect.stringMatching(/^python_api_(contract_error|unavailable)$/),
      })
      await expect(result).rejects.not.toThrow(/secret|traceback|Bearer/)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    }
  })

  it.each([
    "token",
    "authorization",
    "password_hash",
    "request_id",
    "backend_url",
    "membership",
    "internal_metadata",
  ])("rejects extra account success field %s before browser exposure", async (field) => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse({ ...ACCOUNT, [field]: "must-not-leak" }, 201)
    )

    const result = requestCreateAccount(
      { name: "Broker", type: "broker", currency: "EUR" },
      fetchMock
    )

    await expect(result).rejects.toMatchObject({
      status: 502,
      code: "python_api_contract_error",
    })
    await expect(result).rejects.not.toThrow(/must-not-leak/)
  })

  it("rejects an extra field in a list item before browser exposure", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse([{ ...ACCOUNT, internal_metadata: "must-not-leak" }])
    )

    const result = requestAccounts(fetchMock)

    await expect(result).rejects.toMatchObject({
      status: 502,
      code: "python_api_contract_error",
    })
    await expect(result).rejects.not.toThrow(/must-not-leak/)
  })
})
