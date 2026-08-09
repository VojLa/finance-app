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

type ManualInvestmentCreate = components["schemas"]["ManualInvestmentCreateRequest"]

function mapError(status: number, value: unknown): SnapshotWorkflowAdapterError {
  if (status === 422) return validationError()
  if ([403, 404, 409].includes(status) && isSafeErrorEnvelope(value)) {
    return forwardedPythonError(status as 403 | 404 | 409, value.error.code, value.error.message)
  }
  return unavailableError()
}

export function createPythonInvestmentApi(
  identity: ServerIdentity,
  options: PythonApiClientOptions = {}
) {
  const { client, responseData } = createAuthenticatedPythonTransport(identity, options)
  return {
    create(payload: ManualInvestmentCreate) {
      return responseData(client.POST("/api/v1/investments/manual", { body: payload }), mapError)
    },
    detail(symbol: string) {
      return responseData(
        client.GET("/api/v1/investments/symbols/{symbol}", {
          params: { path: { symbol } },
        }),
        mapError
      )
    },
  }
}
