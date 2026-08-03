import "server-only"

import createClient from "openapi-fetch"

import type { paths } from "@/generated/python-api"
import type { PythonApiConfig } from "./config"
import { loadPythonApiConfig } from "./config"
import { contractError, SnapshotWorkflowAdapterError, unavailableError } from "./errors"
import type { ServerIdentity } from "./internal-token"
import { issueInternalToken } from "./internal-token"

type FetchImplementation = typeof fetch
type TokenIssuer = typeof issueInternalToken

export type PythonApiClientOptions = {
  config?: PythonApiConfig
  fetchImplementation?: FetchImplementation
  tokenIssuer?: TokenIssuer
}

export type PythonErrorMapper = (status: number, value: unknown) => SnapshotWorkflowAdapterError

export function isSafeErrorEnvelope(
  value: unknown
): value is { error: { code: string; message: string } } {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false
  }
  const error = value.error
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof error.code === "string" &&
    "message" in error &&
    typeof error.message === "string"
  )
}

function isJsonResponse(response: Response): boolean {
  return response.headers.get("content-type")?.toLowerCase().includes("json") ?? false
}

export function createAuthenticatedPythonTransport(
  identity: ServerIdentity,
  options: PythonApiClientOptions = {}
) {
  const config = options.config ?? loadPythonApiConfig()
  const fetchImplementation = options.fetchImplementation ?? globalThis.fetch
  const tokenIssuer = options.tokenIssuer ?? issueInternalToken

  const authenticatedFetch: FetchImplementation = async (input, init) => {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), config.timeoutMs)
    try {
      const token = await tokenIssuer(identity, config)
      const request = input instanceof Request ? input : new Request(input, init)
      const headers = new Headers({
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
      })
      const requestedContentType = request.headers.get("Content-Type")?.toLowerCase()
      if (requestedContentType === "application/octet-stream") {
        headers.set("Content-Type", "application/octet-stream")
      } else if (["POST", "PATCH"].includes(request.method.toUpperCase())) {
        headers.set("Content-Type", "application/json")
      }
      const response = await fetchImplementation(input, {
        ...init,
        cache: "no-store",
        headers,
        signal: controller.signal,
      })
      if (!isJsonResponse(response)) {
        throw unavailableError()
      }
      return response
    } catch (error) {
      if (error instanceof SnapshotWorkflowAdapterError) {
        throw error
      }
      throw unavailableError()
    } finally {
      clearTimeout(timeout)
    }
  }

  const client = createClient<paths>({
    baseUrl: config.backendUrl,
    fetch: authenticatedFetch,
  })

  async function responseData<T>(
    request: Promise<{
      data?: T
      error?: unknown
      response: Response
    }>,
    mapPythonError: PythonErrorMapper
  ): Promise<T> {
    try {
      const result = await request
      if (!result.response.ok) {
        throw mapPythonError(result.response.status, result.error)
      }
      if (result.data === undefined) {
        throw contractError()
      }
      return result.data
    } catch (error) {
      if (error instanceof SnapshotWorkflowAdapterError) {
        throw error
      }
      throw unavailableError()
    }
  }

  async function rawJsonRequest<T>(
    path: string,
    init: RequestInit,
    mapPythonError: PythonErrorMapper
  ): Promise<T> {
    try {
      const baseUrl = config.backendUrl.replace(/\/+$/, "")
      const url = new URL(`${baseUrl}${path.startsWith("/") ? path : `/${path}`}`)
      const response = await authenticatedFetch(url, init)
      const value: unknown = await response.json()
      if (!response.ok) {
        throw mapPythonError(response.status, value)
      }
      return value as T
    } catch (error) {
      if (error instanceof SnapshotWorkflowAdapterError) {
        throw error
      }
      throw unavailableError()
    }
  }

  return { client, responseData, rawJsonRequest }
}
