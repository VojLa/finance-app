import { getServerSession } from "next-auth"
import type { NextRequest } from "next/server"
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest"

import {
  archiveAccount,
  createAccount,
  listAccounts,
  updateAccount,
} from "@/modules/accounts/server/account-api"
import {
  forwardedPythonError,
  unavailableError,
  validationError,
} from "@/modules/python-api/server/errors"
import * as archiveRoute from "./[id]/archive/route"
import * as updateRoute from "./[id]/route"
import * as collectionRoute from "./route"

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}))

vi.mock("@/lib/auth", () => ({
  authOptions: { providers: [] },
}))

vi.mock("@/modules/accounts/server/account-api", () => ({
  listAccounts: vi.fn(),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  archiveAccount: vi.fn(),
}))

const getSession = vi.mocked(getServerSession)
const list = vi.mocked(listAccounts)
const create = vi.mocked(createAccount)
const update = vi.mocked(updateAccount)
const archive = vi.mocked(archiveAccount)

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

type RouteCase = {
  name: string
  invoke: () => Promise<Response>
  client: Mock
}

function createRequest(): NextRequest {
  return new Request("http://next.test/api/accounts", {
    method: "POST",
    headers: {
      Authorization: "browser-token",
      Cookie: "next-auth=session-cookie",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      name: "Broker",
      type: "broker",
      currency: "EUR",
    }),
  }) as NextRequest
}

function updateRequest(): NextRequest {
  return new Request("http://next.test/api/accounts/caller-body-id", {
    method: "PATCH",
    headers: {
      Authorization: "browser-token",
      Cookie: "next-auth=session-cookie",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ name: "Updated", currency: "USD" }),
  }) as NextRequest
}

const ROUTES: RouteCase[] = [
  {
    name: "list",
    invoke: collectionRoute.GET,
    client: list as unknown as Mock,
  },
  {
    name: "create",
    invoke: () => collectionRoute.POST(createRequest()),
    client: create as unknown as Mock,
  },
  {
    name: "update",
    invoke: () => updateRoute.PATCH(updateRequest(), { params: { id: "path-account" } }),
    client: update as unknown as Mock,
  },
  {
    name: "archive",
    invoke: () =>
      archiveRoute.POST(
        new Request("http://next.test/api/accounts/path-account/archive", {
          method: "POST",
          headers: {
            Authorization: "browser-token",
            Cookie: "next-auth=session-cookie",
          },
        }),
        { params: { id: "path-account" } }
      ),
    client: archive as unknown as Mock,
  },
]

beforeEach(() => {
  vi.clearAllMocks()
})

describe("thin account routes", () => {
  it("exports only GET/POST, PATCH and archive POST", () => {
    expect(Object.keys(collectionRoute).sort()).toEqual(["GET", "POST"])
    expect(Object.keys(updateRoute)).toEqual(["PATCH"])
    expect(Object.keys(archiveRoute)).toEqual(["POST"])
  })

  it.each(ROUTES)(
    "$name rejects a missing session before calling Python",
    async ({ invoke, client }) => {
      getSession.mockResolvedValue(null)

      const response = await invoke()

      expect(getSession).toHaveBeenCalledTimes(1)
      expect(client).not.toHaveBeenCalled()
      expect(response.status).toBe(401)
      expect(response.headers.get("Cache-Control")).toBe("no-store")
      expect(await response.json()).toEqual({
        error: {
          code: "authentication_required",
          message: "Authentication is required.",
        },
      })
    }
  )

  it.each(ROUTES)(
    "$name rejects a blank session identity before calling Python",
    async ({ invoke, client }) => {
      getSession.mockResolvedValue({
        user: { id: " ", email: "user@example.test" },
        expires: "2036-01-01",
      })

      const response = await invoke()

      expect(getSession).toHaveBeenCalledTimes(1)
      expect(client).not.toHaveBeenCalled()
      expect(response.status).toBe(401)
    }
  )

  it("lists once with the exact verified identity", async () => {
    getSession.mockResolvedValue({
      user: { id: "user-1", email: "user@example.test" },
      expires: "2036-01-01",
    })
    list.mockResolvedValue([ACCOUNT])

    const response = await collectionRoute.GET()

    expect(getSession).toHaveBeenCalledTimes(1)
    expect(list).toHaveBeenCalledTimes(1)
    expect(list).toHaveBeenCalledWith({
      userId: "user-1",
      email: "user@example.test",
    })
    expect(response.headers.get("Cache-Control")).toBe("no-store")
    expect(await response.json()).toEqual([ACCOUNT])
  })

  it("creates once with exact body and no caller credentials or server identity fields", async () => {
    getSession.mockResolvedValue({
      user: { id: "user-1", email: null },
      expires: "2036-01-01",
    })
    create.mockResolvedValue(ACCOUNT)

    const response = await collectionRoute.POST(createRequest())

    expect(getSession).toHaveBeenCalledTimes(1)
    expect(create).toHaveBeenCalledTimes(1)
    expect(create).toHaveBeenCalledWith(
      { userId: "user-1", email: undefined },
      { name: "Broker", type: "broker", currency: "EUR" }
    )
    expect(JSON.stringify(create.mock.calls[0]?.[1])).not.toMatch(
      /userId|user_id|membership|browser-token|session-cookie/
    )
    expect(response.status).toBe(201)
    expect(response.headers.get("Cache-Control")).toBe("no-store")
  })

  it("updates once with route ID and a type-free body", async () => {
    getSession.mockResolvedValue({
      user: { id: "user-1", email: "user@example.test" },
      expires: "2036-01-01",
    })
    update.mockResolvedValue({ ...ACCOUNT, name: "Updated", currency: "USD" })

    await updateRoute.PATCH(updateRequest(), { params: { id: "path-account" } })

    expect(getSession).toHaveBeenCalledTimes(1)
    expect(update).toHaveBeenCalledTimes(1)
    expect(update).toHaveBeenCalledWith(
      { userId: "user-1", email: "user@example.test" },
      "path-account",
      { name: "Updated", currency: "USD" }
    )
    expect(JSON.stringify(update.mock.calls[0]?.[2])).not.toContain("type")
  })

  it("archives once without a body or destructive operation", async () => {
    getSession.mockResolvedValue({
      user: { id: "user-1", email: "user@example.test" },
      expires: "2036-01-01",
    })
    archive.mockResolvedValue({ ...ACCOUNT, is_archived: true })

    const response = await archiveRoute.POST(
      new Request("http://next.test/api/accounts/path-account/archive", {
        method: "POST",
        body: "ignored caller body",
      }),
      { params: { id: "path-account" } }
    )

    expect(getSession).toHaveBeenCalledTimes(1)
    expect(archive).toHaveBeenCalledTimes(1)
    expect(archive).toHaveBeenCalledWith(
      { userId: "user-1", email: "user@example.test" },
      "path-account"
    )
    expect(response.headers.get("Cache-Control")).toBe("no-store")
  })

  it.each([
    [validationError(), 422, "validation_error", "Request validation failed."],
    [
      forwardedPythonError(404, "account_not_found", "Account was not found."),
      404,
      "account_not_found",
      "Account was not found.",
    ],
    [
      forwardedPythonError(409, "account_archived", "Account is archived."),
      409,
      "account_archived",
      "Account is archived.",
    ],
    [unavailableError(), 502, "python_api_unavailable", "The Python API is unavailable."],
  ] as const)(
    "returns only the safe mapped error envelope",
    async (error, status, code, message) => {
      getSession.mockResolvedValue({
        user: { id: "user-1", email: "user@example.test" },
        expires: "2036-01-01",
      })
      create.mockRejectedValue(error)

      const response = await collectionRoute.POST(createRequest())

      expect(response.status).toBe(status)
      expect(response.headers.get("Cache-Control")).toBe("no-store")
      expect(await response.json()).toEqual({ error: { code, message } })
    }
  )

  it("maps malformed JSON to stable 422 before calling Python", async () => {
    getSession.mockResolvedValue({
      user: { id: "user-1", email: "user@example.test" },
      expires: "2036-01-01",
    })
    const request = new Request("http://next.test/api/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{",
    }) as NextRequest

    const response = await collectionRoute.POST(request)

    expect(create).not.toHaveBeenCalled()
    expect(response.status).toBe(422)
    expect(await response.json()).toEqual({
      error: { code: "validation_error", message: "Request validation failed." },
    })
  })
})
