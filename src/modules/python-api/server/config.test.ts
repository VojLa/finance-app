import "server-only"

import { describe, expect, it } from "vitest"

import { loadPythonApiConfig } from "./config"

const VALID_ENVIRONMENT = {
  PYTHON_BACKEND_URL: "http://localhost:8010",
  INTERNAL_AUTH_SECRET: "test-internal-auth-secret-with-32-characters",
  INTERNAL_AUTH_ISSUER: "finance-app-next",
  INTERNAL_AUTH_AUDIENCE: "finance-app-python",
  INTERNAL_AUTH_TOKEN_TTL_SECONDS: "60",
  PYTHON_API_TIMEOUT_MS: "30000",
}

function environment(overrides: Record<string, string | undefined> = {}): NodeJS.ProcessEnv {
  return { NODE_ENV: "test", ...VALID_ENVIRONMENT, ...overrides }
}

function expectConfigurationError(overrides: Record<string, string | undefined>) {
  expect(() => loadPythonApiConfig(environment(overrides))).toThrow(
    expect.objectContaining({
      status: 503,
      code: "python_api_configuration_error",
      message: "The Python API adapter is not configured.",
    })
  )
}

describe("loadPythonApiConfig", () => {
  it("loads the exact valid server configuration", () => {
    expect(loadPythonApiConfig(environment())).toEqual({
      backendUrl: "http://localhost:8010",
      internalAuthSecret: VALID_ENVIRONMENT.INTERNAL_AUTH_SECRET,
      internalAuthIssuer: "finance-app-next",
      internalAuthAudience: "finance-app-python",
      internalAuthTokenTtlSeconds: 60,
      timeoutMs: 30000,
    })
  })

  it("uses documented issuer, audience, TTL, and timeout defaults", () => {
    expect(
      loadPythonApiConfig(
        environment({
          INTERNAL_AUTH_ISSUER: undefined,
          INTERNAL_AUTH_AUDIENCE: undefined,
          INTERNAL_AUTH_TOKEN_TTL_SECONDS: undefined,
          PYTHON_API_TIMEOUT_MS: undefined,
        })
      )
    ).toMatchObject({
      internalAuthIssuer: "finance-app-next",
      internalAuthAudience: "finance-app-python",
      internalAuthTokenTtlSeconds: 60,
      timeoutMs: 30000,
    })
  })

  it("rejects a missing backend URL", () => {
    expectConfigurationError({ PYTHON_BACKEND_URL: undefined })
  })

  it.each(["relative/path", "ftp://localhost:8010", "not a URL"])(
    "rejects invalid backend URL %s",
    (value) => {
      expectConfigurationError({ PYTHON_BACKEND_URL: value })
    }
  )

  it.each(["http://user@localhost:8010", "https://user:password@backend.example.test"])(
    "rejects backend URL credentials in %s",
    (value) => {
      expectConfigurationError({ PYTHON_BACKEND_URL: value })
    }
  )

  it("rejects a missing secret", () => {
    expectConfigurationError({ INTERNAL_AUTH_SECRET: undefined })
  })

  it("rejects a whitespace-only secret", () => {
    expectConfigurationError({ INTERNAL_AUTH_SECRET: " ".repeat(32) })
  })

  it("rejects a secret shorter than 32 characters", () => {
    expectConfigurationError({ INTERNAL_AUTH_SECRET: "short-secret" })
  })

  it.each(["", " issuer", "issuer "])("rejects invalid issuer %j", (value) => {
    expectConfigurationError({ INTERNAL_AUTH_ISSUER: value })
  })

  it.each(["", " audience", "audience "])("rejects invalid audience %j", (value) => {
    expectConfigurationError({ INTERNAL_AUTH_AUDIENCE: value })
  })

  it.each(["9", "301", "10.5", "-1", "text"])("rejects invalid TTL %s", (value) => {
    expectConfigurationError({ INTERNAL_AUTH_TOKEN_TTL_SECONDS: value })
  })

  it.each(["999", "120001", "1000.5", "-1", "text"])("rejects invalid timeout %s", (value) => {
    expectConfigurationError({ PYTHON_API_TIMEOUT_MS: value })
  })

  it("does not read NEXT_PUBLIC-prefixed substitutes", () => {
    expectConfigurationError({
      PYTHON_BACKEND_URL: undefined,
      NEXT_PUBLIC_PYTHON_BACKEND_URL: "http://localhost:8010",
    })
  })
})
