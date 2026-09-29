import "server-only"

import { describe, expect, it, vi } from "vitest"

import type { PythonApiConfig } from "./config"
import { createAuthenticatedPythonTransport } from "./transport"

const CONFIG: PythonApiConfig = {
  backendUrl: "https://python.example.test",
  internalAuthSecret: "test-internal-auth-secret-with-32-characters",
  internalAuthIssuer: "finance-app-next",
  internalAuthAudience: "finance-app-python",
  internalAuthTokenTtlSeconds: 60,
  timeoutMs: 30000,
}

describe("authenticated Python transport", () => {
  it("passes through a bodyless 204 without a JSON content type", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () => new Response(null, { status: 204 }))
    const { client } = createAuthenticatedPythonTransport(
      { userId: "user-1" },
      { config: CONFIG, fetchImplementation, tokenIssuer: vi.fn(async () => "token") }
    )

    const result = await client.GET("/api/v1/read-model-version", { params: { query: {} } })

    expect(result.response.status).toBe(204)
    expect(fetchImplementation).toHaveBeenCalledOnce()
  })
})
