import { beforeEach, describe, expect, it, vi } from "vitest"

import { createPythonAuthApi } from "@/modules/auth/server/auth-api"
import { forwardedPythonError, unavailableError } from "@/modules/python-api/server/errors"
import { authorizeCredentials } from "./auth"

vi.mock("@/modules/auth/server/auth-api", () => ({ createPythonAuthApi: vi.fn() }))

const createApi = vi.mocked(createPythonAuthApi)
const verifyCredentials = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  createApi.mockReturnValue({
    verifyCredentials,
    register: vi.fn(),
    changePassword: vi.fn(),
  })
})

describe("NextAuth credential adapter", () => {
  it("returns the Python-authenticated identity", async () => {
    verifyCredentials.mockResolvedValue({
      id: "user-1",
      email: "normalized@example.test",
      name: "User",
    })

    await expect(
      authorizeCredentials({ email: "USER@example.test", password: "password-1" })
    ).resolves.toEqual({ id: "user-1", email: "normalized@example.test", name: "User" })
  })

  it("returns null for invalid credentials but not for backend outages", async () => {
    verifyCredentials.mockRejectedValueOnce(
      forwardedPythonError(401, "invalid_credentials", "Invalid credentials.")
    )
    await expect(
      authorizeCredentials({ email: "user@example.test", password: "wrong-password" })
    ).resolves.toBeNull()

    verifyCredentials.mockRejectedValueOnce(unavailableError())
    await expect(
      authorizeCredentials({ email: "user@example.test", password: "password-1" })
    ).rejects.toMatchObject({ status: 502, code: "python_api_unavailable" })
  })
})
