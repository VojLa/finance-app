import { getServerSession } from "next-auth"
import type { NextRequest } from "next/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { createPythonAuthApi } from "@/modules/auth/server/auth-api"
import { forwardedPythonError } from "@/modules/python-api/server/errors"
import { PUT as changePassword } from "./password/route"
import { POST as register } from "./register/route"

vi.mock("next-auth", () => ({ getServerSession: vi.fn() }))
vi.mock("@/lib/auth", () => ({ authOptions: { providers: [] } }))
vi.mock("@/modules/auth/server/auth-api", () => ({ createPythonAuthApi: vi.fn() }))

const getSession = vi.mocked(getServerSession)
const createApi = vi.mocked(createPythonAuthApi)
const verifyCredentials = vi.fn()
const registerUser = vi.fn()
const changeUserPassword = vi.fn()

function request(path: string, method: string, body: unknown): NextRequest {
  return new Request(`http://next.test${path}`, {
    method,
    headers: {
      Authorization: "browser-token-must-not-forward",
      Cookie: "next-auth=session-cookie",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  }) as NextRequest
}

beforeEach(() => {
  vi.clearAllMocks()
  createApi.mockReturnValue({
    verifyCredentials,
    register: registerUser,
    changePassword: changeUserPassword,
  })
})

describe("authentication routes", () => {
  it("registers through Python with an exact allowlisted payload", async () => {
    registerUser.mockResolvedValue({ id: "user-1", email: "user@example.test", name: "User" })

    const response = await register(
      request("/api/auth/register", "POST", {
        email: "user@example.test",
        password: "password-1",
        name: "User",
        passwordHash: "caller-controlled",
        id: "caller-id",
      })
    )

    expect(response.status).toBe(201)
    expect(response.headers.get("Cache-Control")).toBe("no-store")
    expect(await response.json()).toEqual({ id: "user-1", email: "user@example.test" })
    expect(registerUser).toHaveBeenCalledWith({
      email: "user@example.test",
      password: "password-1",
      name: "User",
    })
  })

  it("does not call Python for an unauthenticated password change", async () => {
    getSession.mockResolvedValue(null)

    const response = await changePassword(
      request("/api/auth/password", "PUT", {
        currentPassword: "old-password",
        newPassword: "new-password",
      })
    )

    expect(response.status).toBe(401)
    expect(changeUserPassword).not.toHaveBeenCalled()
  })

  it("changes only the current user's password through Python", async () => {
    getSession.mockResolvedValue({
      user: { id: "user-1", email: "user@example.test" },
      expires: "2036-01-01T00:00:00.000Z",
    })
    changeUserPassword.mockResolvedValue({ ok: true })

    const response = await changePassword(
      request("/api/auth/password", "PUT", {
        currentPassword: "old-password",
        newPassword: "new-password",
        userId: "foreign-user",
      })
    )

    expect(response.status).toBe(200)
    expect(changeUserPassword).toHaveBeenCalledWith(
      { userId: "user-1", email: "user@example.test" },
      { current_password: "old-password", new_password: "new-password" }
    )
  })

  it("preserves a safe duplicate-email response", async () => {
    registerUser.mockRejectedValue(
      forwardedPythonError(
        409,
        "email_already_registered",
        "The email address is already registered."
      )
    )

    const response = await register(
      request("/api/auth/register", "POST", {
        email: "user@example.test",
        password: "password-1",
      })
    )

    expect(response.status).toBe(409)
    expect(await response.json()).toEqual({ error: "Email již existuje" })
  })
})
