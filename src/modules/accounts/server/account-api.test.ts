import "server-only"

import { afterEach, describe, expect, it, vi } from "vitest"

import type { PythonApiConfig } from "@/modules/python-api/server/config"
import { createPythonAccountApi } from "./account-api"

const CONFIG: PythonApiConfig = {
  backendUrl: "https://python.example.test/base",
  internalAuthSecret: "test-internal-auth-secret-with-32-characters",
  internalAuthIssuer: "finance-app-next",
  internalAuthAudience: "finance-app-python",
  internalAuthTokenTtlSeconds: 60,
  timeoutMs: 30000,
}

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

function requestFrom(input: RequestInfo | URL, init?: RequestInit): Request {
  return new Request(input, init)
}

function setup(
  fetchImplementation: typeof fetch,
  tokenIssuer = vi.fn(async () => "internal-token"),
  config = CONFIG
) {
  return {
    api: createPythonAccountApi(
      { userId: "user-1", email: "user@example.test" },
      { config, fetchImplementation, tokenIssuer }
    ),
    tokenIssuer,
  }
}

afterEach(() => {
  vi.useRealTimers()
})

describe("Python account server client", () => {
  it("lists with an exact bodyless GET and preserves server ordering", async () => {
    const second = { ...ACCOUNT, id: "account-2", name: "Cash" }
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse([second, ACCOUNT]))
    const { api } = setup(fetchImplementation)

    await expect(api.listAccounts()).resolves.toEqual([second, ACCOUNT])

    const request = requestFrom(...fetchImplementation.mock.calls[0])
    expect(request.url).toBe("https://python.example.test/base/api/v1/accounts")
    expect(request.method).toBe("GET")
    expect(await request.text()).toBe("")
  })

  it("creates with the exact generated body and no identity or membership fields", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse(ACCOUNT, 201))
    const { api } = setup(fetchImplementation)
    const payload = {
      name: "Broker",
      type: "broker" as const,
      currency: "EUR",
      color: null,
      notes: null,
    }

    await expect(api.createAccount(payload)).resolves.toEqual(ACCOUNT)

    const request = requestFrom(...fetchImplementation.mock.calls[0])
    expect(request.url).toBe("https://python.example.test/base/api/v1/accounts")
    expect(request.method).toBe("POST")
    expect(JSON.parse(await request.text())).toEqual(payload)
    expect(await new Response(JSON.stringify(payload)).text()).not.toMatch(
      /userId|user_id|membership|relation_type|role/
    )
  })

  it("updates with account ID only in the path and never sends type or identity", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ ...ACCOUNT, name: "Updated", currency: "USD" })
    )
    const { api } = setup(fetchImplementation)

    await api.updateAccount("account/with space", {
      name: "Updated",
      currency: "USD",
    })

    const request = requestFrom(...fetchImplementation.mock.calls[0])
    expect(request.url).toBe(
      "https://python.example.test/base/api/v1/accounts/account%2Fwith%20space"
    )
    expect(request.method).toBe("PATCH")
    const body = await request.text()
    expect(JSON.parse(body)).toEqual({
      name: "Updated",
      currency: "USD",
    })
    expect(body).not.toMatch(/type|userId|user_id|sub/)
  })

  it("archives with a bodyless POST and never issues DELETE", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ ...ACCOUNT, is_archived: true })
    )
    const { api } = setup(fetchImplementation)

    await api.archiveAccount("account-1")

    const request = requestFrom(...fetchImplementation.mock.calls[0])
    expect(request.url).toBe("https://python.example.test/base/api/v1/accounts/account-1/archive")
    expect(request.method).toBe("POST")
    expect(await request.text()).toBe("")
    expect(fetchImplementation).toHaveBeenCalledTimes(1)
  })

  it("issues a fresh token immediately before every account request", async () => {
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([ACCOUNT]))
      .mockResolvedValueOnce(jsonResponse(ACCOUNT))
    const tokenIssuer = vi
      .fn()
      .mockResolvedValueOnce("account-token-1")
      .mockResolvedValueOnce("account-token-2")
    const { api } = setup(fetchImplementation, tokenIssuer)

    await api.listAccounts()
    await api.updateAccount("account-1", { name: "Updated" })

    expect(tokenIssuer).toHaveBeenCalledTimes(2)
    expect(tokenIssuer).toHaveBeenNthCalledWith(
      1,
      { userId: "user-1", email: "user@example.test" },
      CONFIG
    )
    expect(requestFrom(...fetchImplementation.mock.calls[0]).headers.get("Authorization")).toBe(
      "Bearer account-token-1"
    )
    expect(requestFrom(...fetchImplementation.mock.calls[1]).headers.get("Authorization")).toBe(
      "Bearer account-token-2"
    )
  })

  it("uses no-store and replaces browser credentials with server credentials", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse([ACCOUNT]))
    const { api } = setup(fetchImplementation)

    await api.listAccounts()

    const request = requestFrom(...fetchImplementation.mock.calls[0])
    expect(request.headers.get("Authorization")).toBe("Bearer internal-token")
    expect(request.headers.has("Cookie")).toBe(false)
    expect(fetchImplementation.mock.calls[0][1]?.cache).toBe("no-store")
  })

  it("aborts at timeout and does not retry", async () => {
    vi.useFakeTimers()
    const fetchImplementation = vi.fn<typeof fetch>(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError"))
          )
        })
    )
    const { api } = setup(fetchImplementation, undefined, { ...CONFIG, timeoutMs: 1000 })

    const result = api.listAccounts()
    const assertion = expect(result).rejects.toMatchObject({
      status: 502,
      code: "python_api_unavailable",
      message: "The Python API is unavailable.",
    })
    await vi.advanceTimersByTimeAsync(1000)

    await assertion
    expect(fetchImplementation).toHaveBeenCalledTimes(1)
  })

  it.each([
    ["network", async () => Promise.reject(new Error("secret token raw body"))],
    [
      "non-JSON",
      async () =>
        new Response("secret traceback", {
          status: 500,
          headers: { "Content-Type": "text/plain" },
        }),
    ],
    [
      "Python 500",
      async () => jsonResponse({ error: { code: "raw", message: "secret raw body" } }, 500),
    ],
  ])("maps %s to one generic unavailable error without retry", async (_name, response) => {
    const fetchImplementation = vi.fn<typeof fetch>(response)
    const { api } = setup(fetchImplementation)

    const result = api.listAccounts()
    await expect(result).rejects.toMatchObject({
      status: 502,
      code: "python_api_unavailable",
      message: "The Python API is unavailable.",
    })
    await expect(result).rejects.not.toThrow(/secret|traceback|raw body/)
    expect(fetchImplementation).toHaveBeenCalledTimes(1)
  })

  it.each([401, 403])("maps Python %s to an internal bridge failure", async (status) => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ error: { code: "raw_auth", message: "raw auth" } }, status)
    )
    const { api } = setup(fetchImplementation)

    await expect(api.listAccounts()).rejects.toMatchObject({
      status: 502,
      code: "python_api_unavailable",
    })
  })

  it.each([404, 409] as const)("forwards only safe Python %s code and message", async (status) => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse(
        {
          error: {
            code: `account_${status}`,
            message: `Safe ${status}.`,
            request_id: "hidden-request-id",
            traceback: "hidden",
          },
        },
        status
      )
    )
    const { api } = setup(fetchImplementation)

    await expect(api.updateAccount("missing", { name: "No" })).rejects.toMatchObject({
      status,
      code: `account_${status}`,
      message: `Safe ${status}.`,
    })
  })

  it("maps user-authored Python 422 to the stable validation contract", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse(
        {
          error: {
            code: "validation_error",
            message: "raw field details",
            request_id: "hidden",
          },
        },
        422
      )
    )
    const { api } = setup(fetchImplementation)

    await expect(
      api.createAccount({ name: "", type: "bank", currency: "EUR" })
    ).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      message: "Request validation failed.",
    })
  })

  it("fails closed on a missing required success field", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ ...ACCOUNT, relation_type: undefined })
    )
    const { api } = setup(fetchImplementation)

    await expect(
      api.createAccount({ name: "A", type: "bank", currency: "EUR" })
    ).rejects.toMatchObject({
      status: 502,
      code: "python_api_contract_error",
      message: "The Python API returned an incompatible response.",
    })
  })

  it.each([
    "token",
    "authorization",
    "password_hash",
    "request_id",
    "backend_url",
    "membership",
    "internal_metadata",
  ])("rejects extra create success field %s without leaking it", async (field) => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ ...ACCOUNT, [field]: "must-not-leak" }, 201)
    )
    const { api } = setup(fetchImplementation)

    const result = api.createAccount({ name: "A", type: "bank", currency: "EUR" })
    await expect(result).rejects.toMatchObject({
      status: 502,
      code: "python_api_contract_error",
      message: "The Python API returned an incompatible response.",
    })
    await expect(result).rejects.not.toThrow(/must-not-leak/)
  })

  it.each([
    "token",
    "authorization",
    "password_hash",
    "request_id",
    "backend_url",
    "membership",
    "internal_metadata",
  ])("rejects extra list-item success field %s without leaking it", async (field) => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse([{ ...ACCOUNT, [field]: "must-not-leak" }])
    )
    const { api } = setup(fetchImplementation)

    const result = api.listAccounts()
    await expect(result).rejects.toMatchObject({
      status: 502,
      code: "python_api_contract_error",
      message: "The Python API returned an incompatible response.",
    })
    await expect(result).rejects.not.toThrow(/must-not-leak/)
  })

  it.each([
    ["unknown account type", { type: "investment" }],
    ["unknown role", { role: "superuser" }],
    ["unknown relation type", { relation_type: "guest" }],
    ["short currency", { currency: "EU" }],
    ["lowercase currency", { currency: "eur" }],
    ["invalid created timestamp", { created_at: "not-a-date" }],
    ["invalid updated timestamp", { updated_at: "2036-01-01" }],
    ["impossible calendar timestamp", { updated_at: "2036-02-30T00:00:00" }],
  ])("maps %s in a success response to a contract error", async (_name, override) => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse([{ ...ACCOUNT, ...override }])
    )
    const { api } = setup(fetchImplementation)

    await expect(api.listAccounts()).rejects.toMatchObject({
      status: 502,
      code: "python_api_contract_error",
      message: "The Python API returned an incompatible response.",
    })
  })
})
