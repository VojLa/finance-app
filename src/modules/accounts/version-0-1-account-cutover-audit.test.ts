import { jwtVerify } from "jose"
import { getServerSession } from "next-auth"
import type { NextRequest } from "next/server"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import * as archiveRoute from "@/app/api/accounts/[id]/archive/route"
import * as updateRoute from "@/app/api/accounts/[id]/route"
import * as collectionRoute from "@/app/api/accounts/route"
import {
  requestAccounts,
  requestArchiveAccount,
  requestCreateAccount,
  requestUpdateAccount,
} from "./account-client"

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}))

vi.mock("@/lib/auth", () => ({
  authOptions: { providers: [] },
}))

const SECRET = "account-cutover-internal-auth-secret-32-characters"
const ACCOUNT = {
  id: "account-r1",
  name: "R1 broker",
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

const getSession = vi.mocked(getServerSession)

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubEnv("PYTHON_BACKEND_URL", "https://python.example.test")
  vi.stubEnv("INTERNAL_AUTH_SECRET", SECRET)
  vi.stubEnv("INTERNAL_AUTH_ISSUER", "finance-app-next")
  vi.stubEnv("INTERNAL_AUTH_AUDIENCE", "finance-app-python")
  vi.stubEnv("INTERNAL_AUTH_TOKEN_TTL_SECONDS", "60")
  vi.stubEnv("PYTHON_API_TIMEOUT_MS", "30000")
  getSession.mockResolvedValue({
    user: { id: "session-user-r1", email: "r1@example.test" },
    expires: "2036-01-01",
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe("version 0.1 account browser-flow acceptance", () => {
  it("connects browser client through thin Next routes to Python with no Prisma ownership", async () => {
    const serverRequests: Request[] = []
    const pythonAccounts = [ACCOUNT]
    const serverFetch = vi.fn<typeof fetch>(async (input, init) => {
      const request = new Request(input, init)
      serverRequests.push(request.clone())
      const path = new URL(request.url).pathname

      if (path === "/api/v1/accounts" && request.method === "POST") {
        expect(JSON.parse(await request.text())).toEqual({
          name: "R1 broker",
          type: "broker",
          currency: "EUR",
        })
        return jsonResponse(ACCOUNT, 201)
      }
      if (path === "/api/v1/accounts" && request.method === "GET") {
        return jsonResponse(pythonAccounts)
      }
      if (path === "/api/v1/accounts/account-r1" && request.method === "PATCH") {
        expect(JSON.parse(await request.text())).toEqual({
          name: "Updated R1 broker",
          currency: "USD",
        })
        return jsonResponse({ ...ACCOUNT, name: "Updated R1 broker", currency: "USD" })
      }
      if (path === "/api/v1/accounts/account-r1/archive" && request.method === "POST") {
        expect(await request.text()).toBe("")
        return jsonResponse({ ...ACCOUNT, is_archived: true })
      }
      return jsonResponse({ error: { code: "unexpected", message: "Unexpected request." } }, 500)
    })
    vi.stubGlobal("fetch", serverFetch)

    const browserRequests: Request[] = []
    const browserFetch = vi.fn<typeof fetch>(async (input, init) => {
      const path = typeof input === "string" ? input : input.toString()
      const request = new Request(`http://next.test${path}`, init)
      browserRequests.push(request.clone())

      if (path === "/api/accounts" && request.method === "POST") {
        return collectionRoute.POST(request as NextRequest)
      }
      if (path === "/api/accounts" && request.method === "GET") {
        return collectionRoute.GET()
      }
      if (path === "/api/accounts/account-r1" && request.method === "PATCH") {
        return updateRoute.PATCH(request as NextRequest, { params: { id: "account-r1" } })
      }
      if (path === "/api/accounts/account-r1/archive" && request.method === "POST") {
        return archiveRoute.POST(request, { params: { id: "account-r1" } })
      }
      throw new Error(`Unexpected browser path: ${path}`)
    })

    const created = await requestCreateAccount(
      { name: "R1 broker", type: "broker", currency: "EUR" },
      browserFetch
    )
    const listed = await requestAccounts(browserFetch)
    const updated = await requestUpdateAccount(
      "account-r1",
      { name: "Updated R1 broker", currency: "USD" },
      browserFetch
    )
    const archived = await requestArchiveAccount("account-r1", browserFetch)

    expect(created).toEqual(ACCOUNT)
    expect(listed).toEqual(pythonAccounts)
    expect(updated.type).toBe("broker")
    expect(updated.name).toBe("Updated R1 broker")
    expect(archived.is_archived).toBe(true)
    expect(getSession).toHaveBeenCalledTimes(4)
    expect(browserRequests.map((request) => new URL(request.url).pathname)).toEqual([
      "/api/accounts",
      "/api/accounts",
      "/api/accounts/account-r1",
      "/api/accounts/account-r1/archive",
    ])
    expect(serverRequests.map((request) => new URL(request.url).pathname)).toEqual([
      "/api/v1/accounts",
      "/api/v1/accounts",
      "/api/v1/accounts/account-r1",
      "/api/v1/accounts/account-r1/archive",
    ])
    expect(serverRequests.map((request) => request.method)).toEqual([
      "POST",
      "GET",
      "PATCH",
      "POST",
    ])
    expect(serverRequests.every((request) => !request.headers.has("Cookie"))).toBe(true)
    expect(
      JSON.stringify(await Promise.all(browserRequests.map((request) => request.clone().text())))
    ).not.toMatch(/session-user-r1|sub|membership|relation_type|role/)
    expect(JSON.stringify({ created, listed, updated, archived })).not.toMatch(
      /Bearer|internal-auth-secret|jti/
    )

    const verifiedTokens = await Promise.all(
      serverRequests.map(async (request) => {
        const authorization = request.headers.get("Authorization")
        expect(authorization).toMatch(/^Bearer /)
        const token = authorization?.slice("Bearer ".length) ?? ""
        return jwtVerify(token, new TextEncoder().encode(SECRET), {
          algorithms: ["HS256"],
          issuer: "finance-app-next",
          audience: "finance-app-python",
        })
      })
    )
    expect(verifiedTokens.map(({ payload }) => payload.sub)).toEqual([
      "session-user-r1",
      "session-user-r1",
      "session-user-r1",
      "session-user-r1",
    ])
    expect(new Set(verifiedTokens.map(({ payload }) => payload.jti)).size).toBe(4)
    expect(serverFetch).toHaveBeenCalledTimes(4)
    expect(browserFetch).toHaveBeenCalledTimes(4)
  })
})
