import "server-only"

import { jwtVerify } from "jose"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { PythonApiConfig } from "./config"
import { readSnapshotBackedPortfolioHistory } from "./portfolio-history"

const CONFIG: PythonApiConfig = {
  backendUrl: "https://python.example.test/base",
  internalAuthSecret: "test-internal-auth-secret-with-32-characters",
  internalAuthIssuer: "finance-app-next",
  internalAuthAudience: "finance-app-python",
  internalAuthTokenTtlSeconds: 60,
  timeoutMs: 30000,
}
const HISTORY = {
  range: "1Y" as const,
  currency: "EUR",
  points: [
    {
      timestamp: "2036-01-01T00:00:00.000",
      cashValue: "10.000000",
      investmentValue: "20.000000",
      liabilitiesValue: "5.000000",
      netWorthValue: "25.000000",
    },
  ],
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function requestFrom(input: RequestInfo | URL, init?: RequestInit): Request {
  return new Request(input, init)
}

afterEach(() => {
  vi.useRealTimers()
})

describe("snapshot-backed portfolio history transport", () => {
  it("uses the generated GET operation with exact query and server identity", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse(HISTORY))
    const tokenIssuer = vi.fn(async () => "internal-token")

    const result = await readSnapshotBackedPortfolioHistory(
      { userId: "user-1", email: "user@example.test" },
      "1Y",
      { config: CONFIG, fetchImplementation, tokenIssuer }
    )

    expect(result).toEqual(HISTORY)
    expect(tokenIssuer).toHaveBeenCalledOnce()
    expect(tokenIssuer).toHaveBeenCalledWith(
      { userId: "user-1", email: "user@example.test" },
      CONFIG
    )
    const request = requestFrom(...fetchImplementation.mock.calls[0])
    expect(request.url).toBe("https://python.example.test/base/api/v1/portfolio/history?range=1Y")
    expect(request.method).toBe("GET")
    expect(await request.text()).toBe("")
    expect(request.headers.get("Authorization")).toBe("Bearer internal-token")
    expect(request.headers.get("Accept")).toBe("application/json")
    expect(request.headers.has("Cookie")).toBe(false)
    expect(fetchImplementation.mock.calls[0][1]?.cache).toBe("no-store")
  })

  it("creates a fresh bearer token for every request", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse(HISTORY))
    const tokenIssuer = vi
      .fn()
      .mockResolvedValueOnce("token-with-jti-1")
      .mockResolvedValueOnce("token-with-jti-2")

    await readSnapshotBackedPortfolioHistory({ userId: "user-1" }, "1Y", {
      config: CONFIG,
      fetchImplementation,
      tokenIssuer,
    })
    await readSnapshotBackedPortfolioHistory({ userId: "user-1" }, "1Y", {
      config: CONFIG,
      fetchImplementation,
      tokenIssuer,
    })

    expect(tokenIssuer).toHaveBeenCalledTimes(2)
    expect(requestFrom(...fetchImplementation.mock.calls[0]).headers.get("Authorization")).toBe(
      "Bearer token-with-jti-1"
    )
    expect(requestFrom(...fetchImplementation.mock.calls[1]).headers.get("Authorization")).toBe(
      "Bearer token-with-jti-2"
    )
  })

  it("issues fresh JWT identities with distinct JTI values", async () => {
    const authorizations: string[] = []
    const fetchImplementation = vi.fn<typeof fetch>(async (input, init) => {
      authorizations.push(requestFrom(input, init).headers.get("Authorization") ?? "")
      return jsonResponse(HISTORY)
    })

    for (const range of ["1Y", "1Y"] as const) {
      await readSnapshotBackedPortfolioHistory(
        { userId: "user-1", email: "user@example.test" },
        range,
        { config: CONFIG, fetchImplementation }
      )
    }

    const payloads = await Promise.all(
      authorizations.map(async (authorization) => {
        const token = authorization.slice("Bearer ".length)
        return (
          await jwtVerify(token, new TextEncoder().encode(CONFIG.internalAuthSecret), {
            algorithms: ["HS256"],
            issuer: CONFIG.internalAuthIssuer,
            audience: CONFIG.internalAuthAudience,
          })
        ).payload
      })
    )
    expect(payloads.map((payload) => payload.sub)).toEqual(["user-1", "user-1"])
    expect(payloads.map((payload) => payload.email)).toEqual([
      "user@example.test",
      "user@example.test",
    ])
    expect(payloads[0]?.jti).toBeTruthy()
    expect(payloads[1]?.jti).toBeTruthy()
    expect(payloads[0]?.jti).not.toBe(payloads[1]?.jti)
  })

  it("rejects malformed success as a contract error", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ ...HISTORY, raw: "secret" })
    )

    await expect(
      readSnapshotBackedPortfolioHistory({ userId: "user-1" }, "1Y", {
        config: CONFIG,
        fetchImplementation,
        tokenIssuer: vi.fn(async () => "token"),
      })
    ).rejects.toMatchObject({
      status: 502,
      code: "python_api_contract_error",
      message: "The Python API returned an incompatible response.",
    })
  })

  it("forwards only the approved safe 409 envelope", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse(
        {
          error: {
            code: "portfolio_history_unavailable",
            message: "Portfolio history is unavailable.",
            request_id: "hidden",
          },
        },
        409
      )
    )

    await expect(
      readSnapshotBackedPortfolioHistory({ userId: "user-1" }, "1Y", {
        config: CONFIG,
        fetchImplementation,
        tokenIssuer: vi.fn(async () => "token"),
      })
    ).rejects.toMatchObject({
      status: 409,
      code: "portfolio_history_unavailable",
      message: "Portfolio history is unavailable.",
    })
  })

  it("maps safe 422 to the stable transport validation error", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ error: { code: "validation_error", message: "Raw backend validation." } }, 422)
    )

    await expect(
      readSnapshotBackedPortfolioHistory({ userId: "user-1" }, "1Y", {
        config: CONFIG,
        fetchImplementation,
        tokenIssuer: vi.fn(async () => "token"),
      })
    ).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      message: "Request validation failed.",
    })
  })

  it.each([401, 403, 404, 500])("maps Python %s to unavailable", async (status) => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ detail: "raw secret" }, status)
    )

    await expect(
      readSnapshotBackedPortfolioHistory({ userId: "user-1" }, "1Y", {
        config: CONFIG,
        fetchImplementation,
        tokenIssuer: vi.fn(async () => "token"),
      })
    ).rejects.toMatchObject({
      status: 502,
      code: "python_api_unavailable",
      message: "The Python API is unavailable.",
    })
  })

  it("maps non-JSON and network failures without leaking backend URL or token", async () => {
    const token = "secret-bearer-token"
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response("raw traceback", {
          status: 500,
          headers: { "Content-Type": "text/plain" },
        })
      )
      .mockRejectedValueOnce(new Error(`${CONFIG.backendUrl} ${token}`))
    const options = {
      config: CONFIG,
      fetchImplementation,
      tokenIssuer: vi.fn(async () => token),
    }

    for (const attempt of [1, 2]) {
      const result = readSnapshotBackedPortfolioHistory({ userId: "user-1" }, "1Y", options)
      await expect(result).rejects.toHaveProperty("message", "The Python API is unavailable.")
      await expect(result).rejects.not.toThrow(CONFIG.backendUrl)
      await expect(result).rejects.not.toThrow(token)
      expect(fetchImplementation).toHaveBeenCalledTimes(attempt)
    }
  })

  it("aborts at the configured timeout without retry", async () => {
    vi.useFakeTimers()
    const fetchImplementation = vi.fn<typeof fetch>(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError"))
          )
        })
    )
    const result = readSnapshotBackedPortfolioHistory({ userId: "user-1" }, "1Y", {
      config: { ...CONFIG, timeoutMs: 1000 },
      fetchImplementation,
      tokenIssuer: vi.fn(async () => "token"),
    })
    const assertion = expect(result).rejects.toMatchObject({
      status: 502,
      code: "python_api_unavailable",
    })

    await vi.advanceTimersByTimeAsync(1000)

    await assertion
    expect(fetchImplementation).toHaveBeenCalledOnce()
  })
})
