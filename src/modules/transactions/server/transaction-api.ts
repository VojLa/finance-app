import "server-only"

import type { components } from "@/generated/python-api"
import type { ServerIdentity } from "@/modules/python-api/server/internal-token"
import {
  contractError,
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

type TransactionCreate = components["schemas"]["TransactionCreateRequest"]
type TransactionUpdate = components["schemas"]["TransactionUpdateRequest"]
type TransactionDelete = components["schemas"]["TransactionDeleteRequest"]

function mapError(status: number, value: unknown): SnapshotWorkflowAdapterError {
  if (status === 422) return validationError()
  if ([403, 404, 409].includes(status) && isSafeErrorEnvelope(value)) {
    return forwardedPythonError(status as 403 | 404 | 409, value.error.code, value.error.message)
  }
  if (status >= 200 && status < 300) return contractError()
  return unavailableError()
}

export function createPythonTransactionApi(
  identity: ServerIdentity,
  options: PythonApiClientOptions = {}
) {
  const { client, responseData } = createAuthenticatedPythonTransport(identity, options)
  return {
    list(params: {
      page: number
      type?: "income" | "expense" | "transfer"
      categoryId?: string
      accountId?: string
      q?: string
    }) {
      return responseData(
        client.GET("/api/v1/transactions", { params: { query: params } }),
        mapError
      )
    },
    create(payload: TransactionCreate) {
      return responseData(client.POST("/api/v1/transactions", { body: payload }), mapError)
    },
    update(transactionId: string, payload: TransactionUpdate) {
      return responseData(
        client.PATCH("/api/v1/transactions/{transaction_id}", {
          params: { path: { transaction_id: transactionId } },
          body: payload,
        }),
        mapError
      )
    },
    delete(transactionId: string, payload: TransactionDelete) {
      return responseData(
        client.DELETE("/api/v1/transactions/{transaction_id}", {
          params: { path: { transaction_id: transactionId } },
          body: payload,
        }),
        mapError
      )
    },
  }
}
