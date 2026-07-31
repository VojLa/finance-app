import "server-only"

import createClient from "openapi-fetch"

import type { paths } from "@/generated/python-api"
import type {
  DashboardSnapshotData,
  ExactPortfolioSnapshotManifest,
  PortfolioSnapshotData,
  PythonSnapshotRefreshResponse,
} from "../snapshot-workflow-contract"
import type { PythonApiConfig } from "./config"
import { loadPythonApiConfig } from "./config"
import {
  contractError,
  forwardedPythonError,
  SnapshotWorkflowAdapterError,
  unavailableError,
} from "./errors"
import type { ServerIdentity } from "./internal-token"
import { issueInternalToken } from "./internal-token"

type FetchImplementation = typeof fetch
type TokenIssuer = typeof issueInternalToken

export type PythonSnapshotApi = {
  recalculateSnapshotRefresh(): Promise<PythonSnapshotRefreshResponse>
  readPortfolioSnapshot(manifest: ExactPortfolioSnapshotManifest): Promise<PortfolioSnapshotData>
  readDashboardSnapshot(manifest: ExactPortfolioSnapshotManifest): Promise<DashboardSnapshotData>
}

export type PythonApiClientOptions = {
  config?: PythonApiConfig
  fetchImplementation?: FetchImplementation
  tokenIssuer?: TokenIssuer
}

function isJsonResponse(response: Response): boolean {
  return response.headers.get("content-type")?.toLowerCase().includes("json") ?? false
}

function isSafeErrorEnvelope(
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

function mapPythonError(status: number, value: unknown): SnapshotWorkflowAdapterError {
  if (status === 422) {
    return contractError()
  }
  if (status === 404 || status === 409) {
    if (!isSafeErrorEnvelope(value)) {
      return contractError()
    }
    return forwardedPythonError(status, value.error.code, value.error.message)
  }
  return unavailableError()
}

export function createPythonSnapshotApi(
  identity: ServerIdentity,
  options: PythonApiClientOptions = {}
): PythonSnapshotApi {
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
      if (request.method.toUpperCase() === "POST") {
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
    }>
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

  return {
    recalculateSnapshotRefresh() {
      return responseData(client.POST("/api/v1/snapshot-refresh/recalculate", {}))
    },
    readPortfolioSnapshot(manifest) {
      return responseData(
        client.POST("/api/v1/portfolio/snapshot", {
          body: manifest,
        })
      )
    },
    readDashboardSnapshot(manifest) {
      return responseData(
        client.POST("/api/v1/dashboard/snapshot", {
          body: manifest,
        })
      )
    },
  }
}
