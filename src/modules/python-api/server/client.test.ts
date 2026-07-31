import "server-only"

import { afterEach, describe, expect, it, vi } from "vitest"

import type { PythonApiConfig } from "./config"
import { createPythonSnapshotApi } from "./client"

const CONFIG: PythonApiConfig = {
  backendUrl: "https://python.example.test/base",
  internalAuthSecret: "test-internal-auth-secret-with-32-characters",
  internalAuthIssuer: "finance-app-next",
  internalAuthAudience: "finance-app-python",
  internalAuthTokenTtlSeconds: 60,
  timeoutMs: 30000,
}

const REFRESH_RESPONSE = {
  netWorthSnapshotId: "net-worth-1",
  netWorthStatus: "created",
  timestamp: "2036-01-02T03:04:00.000",
  granularity: "minute",
  currency: "EUR",
  calculationVersion: 1,
  accounts: [],
  refreshAccountCount: 0,
  reuseOnlyAccountCount: 0,
  createdAccountSnapshotCount: 0,
  replayedAccountSnapshotCount: 0,
  reusedAccountSnapshotCount: 0,
  selectedAccountSnapshotCount: 0,
}

const MANIFEST = {
  timestamp: "2036-01-02T03:04:00.000",
  granularity: "minute" as const,
  currency: "EUR",
  calculationVersion: 1,
  accounts: [{ accountId: "account-1", snapshotId: "snapshot-1" }],
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

function client(
  fetchImplementation: typeof fetch,
  tokenIssuer = vi.fn(async () => "internal-token"),
  config = CONFIG
) {
  return {
    api: createPythonSnapshotApi(
      { userId: "user-1", email: "user@example.test" },
      { config, fetchImplementation, tokenIssuer }
    ),
    tokenIssuer,
  }
}

afterEach(() => {
  vi.useRealTimers()
})

describe("createPythonSnapshotApi", () => {
  it("uses the exact base URL and refresh path", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse(REFRESH_RESPONSE))
    const { api } = client(fetchImplementation)

    await api.recalculateSnapshotRefresh()

    const request = requestFrom(...fetchImplementation.mock.calls[0])
    expect(request.url).toBe("https://python.example.test/base/api/v1/snapshot-refresh/recalculate")
    expect(request.method).toBe("POST")
    expect(await request.text()).toBe("")
  })

  it.each([
    ["portfolio", "/api/v1/portfolio/snapshot"],
    ["dashboard", "/api/v1/dashboard/snapshot"],
  ] as const)("uses the exact %s path and exact JSON manifest", async (kind, path) => {
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse({ ok: true }))
    const { api } = client(fetchImplementation)

    if (kind === "portfolio") {
      await api.readPortfolioSnapshot(MANIFEST)
    } else {
      await api.readDashboardSnapshot(MANIFEST)
    }

    const request = requestFrom(...fetchImplementation.mock.calls[0])
    expect(request.url).toBe(`https://python.example.test/base${path}`)
    expect(JSON.parse(await request.text())).toEqual(MANIFEST)
  })

  it("sets a bearer token, JSON headers, and no-store without cookies", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse(REFRESH_RESPONSE))
    const { api } = client(fetchImplementation)

    await api.recalculateSnapshotRefresh()

    const request = requestFrom(...fetchImplementation.mock.calls[0])
    expect(request.headers.get("Authorization")).toBe("Bearer internal-token")
    expect(request.headers.get("Accept")).toBe("application/json")
    expect(request.headers.get("Content-Type")).toBe("application/json")
    expect(request.headers.has("Cookie")).toBe(false)
    expect(fetchImplementation.mock.calls[0][1]?.cache).toBe("no-store")
  })

  it("creates a new token immediately before every FastAPI request", async () => {
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(REFRESH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ ok: true }))
    const tokenIssuer = vi
      .fn()
      .mockResolvedValueOnce("request-token-1")
      .mockResolvedValueOnce("request-token-2")
    const { api } = client(fetchImplementation, tokenIssuer)

    await api.recalculateSnapshotRefresh()
    await api.readPortfolioSnapshot(MANIFEST)

    expect(tokenIssuer).toHaveBeenCalledTimes(2)
    expect(requestFrom(...fetchImplementation.mock.calls[0]).headers.get("Authorization")).toBe(
      "Bearer request-token-1"
    )
    expect(requestFrom(...fetchImplementation.mock.calls[1]).headers.get("Authorization")).toBe(
      "Bearer request-token-2"
    )
  })

  it("does not accept or forward a browser Authorization header", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse(REFRESH_RESPONSE))
    const { api } = client(
      fetchImplementation,
      vi.fn(async () => "server-issued")
    )

    await api.recalculateSnapshotRefresh()

    const request = requestFrom(...fetchImplementation.mock.calls[0])
    expect(request.headers.get("Authorization")).toBe("Bearer server-issued")
    expect([...request.headers]).not.toContainEqual(["authorization", "browser-token"])
  })

  it("aborts a request at the configured timeout", async () => {
    vi.useFakeTimers()
    const fetchImplementation = vi.fn<typeof fetch>(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError"))
          )
        })
    )
    const { api } = client(fetchImplementation, undefined, {
      ...CONFIG,
      timeoutMs: 1000,
    })

    const result = api.recalculateSnapshotRefresh()
    const assertion = expect(result).rejects.toMatchObject({
      status: 502,
      code: "python_api_unavailable",
      message: "The Python API is unavailable.",
    })
    await vi.advanceTimersByTimeAsync(1000)

    await assertion
    expect(fetchImplementation).toHaveBeenCalledTimes(1)
  })

  it("maps a network failure to a generic unavailable error without retry", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () => {
      throw new Error("connect ECONNREFUSED secret raw body")
    })
    const { api } = client(fetchImplementation)

    await expect(api.recalculateSnapshotRefresh()).rejects.toMatchObject({
      status: 502,
      code: "python_api_unavailable",
      message: "The Python API is unavailable.",
    })
    expect(fetchImplementation).toHaveBeenCalledTimes(1)
  })

  it("maps a non-JSON response to unavailable without exposing the raw body", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(
      async () =>
        new Response("secret internal traceback", {
          status: 500,
          headers: { "Content-Type": "text/plain" },
        })
    )
    const { api } = client(fetchImplementation)

    const result = api.recalculateSnapshotRefresh()
    await expect(result).rejects.toMatchObject({
      status: 502,
      code: "python_api_unavailable",
      message: "The Python API is unavailable.",
    })
    await expect(result).rejects.not.toThrow("secret internal traceback")
  })

  it.each([404, 409] as const)(
    "forwards a safe Python %s error without request_id",
    async (status) => {
      const fetchImplementation = vi.fn<typeof fetch>(async () =>
        jsonResponse(
          {
            error: {
              code: `safe_${status}`,
              message: `Safe ${status}.`,
              request_id: "internal-request-id",
            },
          },
          status
        )
      )
      const { api } = client(fetchImplementation)

      await expect(api.recalculateSnapshotRefresh()).rejects.toMatchObject({
        status,
        code: `safe_${status}`,
        message: `Safe ${status}.`,
      })
    }
  )

  it.each([401, 403])("maps Python %s after a valid session to internal 502", async (status) => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ error: { code: "backend_auth", message: "raw auth detail" } }, status)
    )
    const { api } = client(fetchImplementation)

    await expect(api.recalculateSnapshotRefresh()).rejects.toMatchObject({
      status: 502,
      code: "python_api_unavailable",
      message: "The Python API is unavailable.",
    })
  })

  it("maps server-owned manifest 422 to a contract error", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ error: { code: "validation_error", message: "raw validation" } }, 422)
    )
    const { api } = client(fetchImplementation)

    await expect(api.readPortfolioSnapshot(MANIFEST)).rejects.toMatchObject({
      status: 502,
      code: "python_api_contract_error",
      message: "The Python API returned an incompatible response.",
    })
  })

  it.each([500, 502, 503])("maps Python %s to unavailable", async (status) => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ error: { code: "raw", message: "internal raw body" } }, status)
    )
    const { api } = client(fetchImplementation)

    await expect(api.recalculateSnapshotRefresh()).rejects.toMatchObject({
      status: 502,
      code: "python_api_unavailable",
      message: "The Python API is unavailable.",
    })
  })

  it("maps malformed safe-error envelopes to a generic contract error", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ error: { code: "leak", traceback: "secret" } }, 409)
    )
    const { api } = client(fetchImplementation)

    await expect(api.recalculateSnapshotRefresh()).rejects.toMatchObject({
      status: 502,
      code: "python_api_contract_error",
      message: "The Python API returned an incompatible response.",
    })
  })

  it("never includes a token in an error message", async () => {
    const token = "super-secret-request-token"
    const fetchImplementation = vi.fn<typeof fetch>(async () => {
      throw new Error(token)
    })
    const { api } = client(
      fetchImplementation,
      vi.fn(async () => token)
    )

    const result = api.recalculateSnapshotRefresh()
    await expect(result).rejects.toHaveProperty("message", "The Python API is unavailable.")
    await expect(result).rejects.not.toThrow(token)
  })
})
