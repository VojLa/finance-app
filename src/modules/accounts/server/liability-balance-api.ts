import "server-only"

import type {
  CreateManualLiabilityBalanceRequest,
  ManualLiabilityBalanceResponse,
} from "../liability-balance-contract"
import { parseManualLiabilityBalanceResponse } from "../liability-balance-contract"
import {
  contractError,
  forwardedPythonError,
  type SnapshotWorkflowAdapterError,
  unavailableError,
  validationError,
} from "@/modules/python-api/server/errors"
import type { ServerIdentity } from "@/modules/python-api/server/internal-token"
import {
  createAuthenticatedPythonTransport,
  isSafeErrorEnvelope,
  type PythonApiClientOptions,
} from "@/modules/python-api/server/transport"

function mapLiabilityPythonError(status: number, value: unknown): SnapshotWorkflowAdapterError {
  if (status === 422) {
    return validationError()
  }
  if (status === 404 || status === 409) {
    if (!isSafeErrorEnvelope(value)) {
      return contractError()
    }
    return forwardedPythonError(status, value.error.code, value.error.message)
  }
  return unavailableError()
}

export function createPythonLiabilityBalanceApi(
  identity: ServerIdentity,
  options: PythonApiClientOptions = {}
) {
  const { client, responseData } = createAuthenticatedPythonTransport(identity, options)
  return {
    async createManualLiabilityBalance(
      accountId: string,
      payload: CreateManualLiabilityBalanceRequest
    ): Promise<ManualLiabilityBalanceResponse> {
      const value = await responseData(
        client.POST("/api/v1/accounts/{account_id}/liability-balances", {
          params: { path: { account_id: accountId } },
          body: payload,
        }),
        mapLiabilityPythonError
      )
      try {
        return parseManualLiabilityBalanceResponse(value)
      } catch {
        throw contractError()
      }
    },
  }
}

export function createManualLiabilityBalance(
  identity: ServerIdentity,
  accountId: string,
  payload: CreateManualLiabilityBalanceRequest,
  options?: PythonApiClientOptions
): Promise<ManualLiabilityBalanceResponse> {
  return createPythonLiabilityBalanceApi(identity, options).createManualLiabilityBalance(
    accountId,
    payload
  )
}
