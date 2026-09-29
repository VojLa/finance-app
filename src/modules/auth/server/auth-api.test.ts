import "server-only"

import { describe, expect, it, vi } from "vitest"

import type { PythonApiConfig } from "@/modules/python-api/server/config"
import type { SnapshotWorkflowAdapterError } from "@/modules/python-api/server/errors"
import { createPythonAuthApi } from "./auth-api"

const CONFIG: PythonApiConfig = {
  backendUrl: "https://python.example.test",
  internalAuthSecret: "test-internal-auth-secret-with-32-characters",
  internalAuthIssuer: "finance-app-next",
  internalAuthAudience: "finance-app-python",
  internalAuthTokenTtlSeconds: 60,
  timeoutMs: 30000,
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("Python authentication server client", () => {
  it("uses the dedicated service identity for credential verification", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ id: "user-1", email: "user@example.test", name: null })
    )
    const tokenIssuer = vi.fn(async () => "service-token")
    const api = createPythonAuthApi({ config: CONFIG, fetchImplementation, tokenIssuer })

    await expect(
      api.verifyCredentials({ email: "user@example.test", password: "password-1" })
    ).resolves.toEqual({ id: "user-1", email: "user@example.test", name: null })

    expect(tokenIssuer).toHaveBeenCalledWith({ userId: "finance-app-next-auth-service" }, CONFIG)
    const request = new Request(...fetchImplementation.mock.calls[0])
    expect(request.method).toBe("POST")
    expect(request.url).toBe("https://python.example.test/api/v1/auth/credentials/verify")
    expect(request.headers.get("Authorization")).toBe("Bearer service-token")
    expect(JSON.parse(await request.text())).toEqual({
      email: "user@example.test",
      password: "password-1",
    })
  })

  it("uses the authenticated user identity and a JSON PUT for password changes", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse({ ok: true }))
    const tokenIssuer = vi.fn(async () => "user-token")
    const api = createPythonAuthApi({ config: CONFIG, fetchImplementation, tokenIssuer })

    await expect(
      api.changePassword(
        { userId: "user-1", email: "user@example.test" },
        { current_password: "old-password", new_password: "new-password" }
      )
    ).resolves.toEqual({ ok: true })

    expect(tokenIssuer).toHaveBeenLastCalledWith(
      { userId: "user-1", email: "user@example.test" },
      CONFIG
    )
    const request = new Request(...fetchImplementation.mock.calls[0])
    expect(request.method).toBe("PUT")
    expect(request.headers.get("Content-Type")).toBe("application/json")
    expect(JSON.parse(await request.text())).toEqual({
      current_password: "old-password",
      new_password: "new-password",
    })
  })

  it("forwards only the safe invalid-credential envelope", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse(
        { error: { code: "invalid_credentials", message: "The email or password is invalid." } },
        401
      )
    )
    const api = createPythonAuthApi({
      config: CONFIG,
      fetchImplementation,
      tokenIssuer: vi.fn(async () => "service-token"),
    })

    await expect(
      api.verifyCredentials({ email: "user@example.test", password: "wrong-password" })
    ).rejects.toMatchObject({
      status: 401,
      code: "invalid_credentials",
    } satisfies Partial<SnapshotWorkflowAdapterError>)
  })
})
