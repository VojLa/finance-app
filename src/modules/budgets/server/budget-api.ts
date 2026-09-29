import "server-only"

import type { components } from "@/generated/python-api"
import type { ServerIdentity } from "@/modules/python-api/server/internal-token"
import {
  forwardedPythonError,
  type SnapshotWorkflowAdapterError,
  unavailableError,
  validationError,
} from "@/modules/python-api/server/errors"
import {
  createAuthenticatedPythonTransport,
  isSafeErrorEnvelope,
  type PythonApiClientOptions,
} from "@/modules/python-api/server/transport"

type BudgetSave = components["schemas"]["BudgetSaveRequest"]

function mapError(status: number, value: unknown): SnapshotWorkflowAdapterError {
  if (status === 422) return validationError()
  if (status === 409 && isSafeErrorEnvelope(value)) {
    return forwardedPythonError(409, value.error.code, value.error.message)
  }
  return unavailableError()
}

export function createPythonBudgetApi(
  identity: ServerIdentity,
  options: PythonApiClientOptions = {}
) {
  const { client, responseData } = createAuthenticatedPythonTransport(identity, options)
  return {
    get(month: number, year: number) {
      return responseData(
        client.GET("/api/v1/budgets/monthly", {
          params: { query: { month, year } },
        }),
        mapError
      )
    },
    save(payload: BudgetSave) {
      return responseData(client.PUT("/api/v1/budgets/monthly", { body: payload }), mapError)
    },
  }
}
