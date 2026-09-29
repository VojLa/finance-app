import "server-only"

import type {
  ExactPortfolioSnapshotManifest,
  LegacyDashboardSnapshotData,
  LegacyPortfolioSnapshotData,
  PythonCurrentDashboardResponse,
  PythonCurrentPortfolioResponse,
  PythonSnapshotRefreshResponse,
} from "../snapshot-workflow-contract"
import {
  contractError,
  forwardedPythonError,
  type SnapshotWorkflowAdapterError,
  unavailableError,
} from "./errors"
import type { ServerIdentity } from "./internal-token"
import {
  createAuthenticatedPythonTransport,
  isSafeErrorEnvelope,
  type PythonApiClientOptions,
} from "./transport"

export type { PythonApiClientOptions } from "./transport"

export type PythonSnapshotApi = {
  recalculateSnapshotRefresh(): Promise<PythonSnapshotRefreshResponse>
  readPortfolioSnapshot(
    manifest: ExactPortfolioSnapshotManifest
  ): Promise<LegacyPortfolioSnapshotData>
  readDashboardSnapshot(
    manifest: ExactPortfolioSnapshotManifest
  ): Promise<LegacyDashboardSnapshotData>
  readCurrentPortfolio(): Promise<PythonCurrentPortfolioResponse>
  readCurrentDashboard(): Promise<PythonCurrentDashboardResponse>
  readPublishedPortfolio(): Promise<PythonCurrentPortfolioResponse>
  readPublishedDashboard(): Promise<PythonCurrentDashboardResponse>
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
  const { client, responseData } = createAuthenticatedPythonTransport(identity, options)

  return {
    recalculateSnapshotRefresh() {
      return responseData(client.POST("/api/v1/snapshot-refresh/recalculate", {}), mapPythonError)
    },
    readPortfolioSnapshot(manifest) {
      return responseData(
        client.POST("/api/v1/portfolio/snapshot", {
          body: manifest,
        }),
        mapPythonError
      )
    },
    readDashboardSnapshot(manifest) {
      return responseData(
        client.POST("/api/v1/dashboard/snapshot", {
          body: manifest,
        }),
        mapPythonError
      )
    },
    readCurrentPortfolio() {
      return responseData(client.POST("/api/v1/portfolio/current", {}), mapPythonError)
    },
    readCurrentDashboard() {
      return responseData(client.POST("/api/v1/dashboard/current", {}), mapPythonError)
    },
    readPublishedPortfolio() {
      return responseData(client.POST("/api/v1/portfolio/published", {}), mapPythonError)
    },
    readPublishedDashboard() {
      return responseData(client.POST("/api/v1/dashboard/published", {}), mapPythonError)
    },
  }
}
