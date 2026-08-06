import "server-only"

import type {
  SnapshotPortfolioHistoryRange,
  SnapshotPortfolioHistoryResponse,
} from "@/modules/portfolio/snapshot-history-contract"
import {
  parseSnapshotPortfolioHistory,
  SnapshotPortfolioHistoryContractError,
} from "@/modules/portfolio/snapshot-history-contract"
import {
  contractError,
  forwardedPythonError,
  type SnapshotWorkflowAdapterError,
  unavailableError,
  validationError,
} from "./errors"
import {
  createAuthenticatedPythonTransport,
  isSafeErrorEnvelope,
  type PythonApiClientOptions,
} from "./transport"

export type PortfolioHistoryIdentity = Readonly<{
  userId: string
  email?: string
}>

function mapPythonError(status: number, value: unknown): SnapshotWorkflowAdapterError {
  if (status === 409) {
    if (!isSafeErrorEnvelope(value) || value.error.code !== "portfolio_history_unavailable") {
      return contractError()
    }
    return forwardedPythonError(409, value.error.code, value.error.message)
  }
  if (status === 422) {
    if (!isSafeErrorEnvelope(value) || value.error.code !== "validation_error") {
      return contractError()
    }
    return validationError()
  }
  return unavailableError()
}

export async function readSnapshotBackedPortfolioHistory(
  identity: PortfolioHistoryIdentity,
  range: SnapshotPortfolioHistoryRange,
  options: PythonApiClientOptions = {}
): Promise<SnapshotPortfolioHistoryResponse> {
  const { client, responseData } = createAuthenticatedPythonTransport(identity, options)
  const value = await responseData(
    client.GET("/api/v1/portfolio/history", {
      params: { query: { range } },
    }),
    mapPythonError
  )
  try {
    return parseSnapshotPortfolioHistory(value, range)
  } catch (error) {
    if (error instanceof SnapshotPortfolioHistoryContractError) {
      throw contractError()
    }
    throw error
  }
}
