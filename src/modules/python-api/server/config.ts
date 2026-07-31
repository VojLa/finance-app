import "server-only"

import { configurationError } from "./errors"

const DEFAULT_ISSUER = "finance-app-next"
const DEFAULT_AUDIENCE = "finance-app-python"
const DEFAULT_TOKEN_TTL_SECONDS = "60"
const DEFAULT_TIMEOUT_MS = "30000"

export type PythonApiConfig = {
  backendUrl: string
  internalAuthSecret: string
  internalAuthIssuer: string
  internalAuthAudience: string
  internalAuthTokenTtlSeconds: number
  timeoutMs: number
}

function requiredValue(value: string | undefined): string {
  if (value === undefined || value.trim().length === 0) {
    throw configurationError()
  }
  return value
}

function trimmedValue(value: string | undefined, fallback: string): string {
  const resolved = value ?? fallback
  if (resolved.length === 0 || resolved !== resolved.trim()) {
    throw configurationError()
  }
  return resolved
}

function boundedInteger(
  value: string | undefined,
  fallback: string,
  minimum: number,
  maximum: number
) {
  const resolved = value ?? fallback
  if (!/^(0|[1-9]\d*)$/.test(resolved)) {
    throw configurationError()
  }
  const parsed = Number(resolved)
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw configurationError()
  }
  return parsed
}

export function loadPythonApiConfig(environment: NodeJS.ProcessEnv = process.env): PythonApiConfig {
  const rawBackendUrl = requiredValue(environment.PYTHON_BACKEND_URL)
  let backendUrl: URL
  try {
    backendUrl = new URL(rawBackendUrl)
  } catch {
    throw configurationError()
  }
  if (
    !["http:", "https:"].includes(backendUrl.protocol) ||
    backendUrl.username.length > 0 ||
    backendUrl.password.length > 0
  ) {
    throw configurationError()
  }

  const internalAuthSecret = requiredValue(environment.INTERNAL_AUTH_SECRET)
  if (internalAuthSecret.length < 32) {
    throw configurationError()
  }

  return {
    backendUrl: backendUrl.toString().replace(/\/$/, ""),
    internalAuthSecret,
    internalAuthIssuer: trimmedValue(environment.INTERNAL_AUTH_ISSUER, DEFAULT_ISSUER),
    internalAuthAudience: trimmedValue(environment.INTERNAL_AUTH_AUDIENCE, DEFAULT_AUDIENCE),
    internalAuthTokenTtlSeconds: boundedInteger(
      environment.INTERNAL_AUTH_TOKEN_TTL_SECONDS,
      DEFAULT_TOKEN_TTL_SECONDS,
      10,
      300
    ),
    timeoutMs: boundedInteger(environment.PYTHON_API_TIMEOUT_MS, DEFAULT_TIMEOUT_MS, 1000, 120000),
  }
}
