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

type CategoryCreate = components["schemas"]["CategoryCreateRequest"]
type CategoryUpdate = components["schemas"]["CategoryUpdateRequest"]

function mapError(status: number, value: unknown): SnapshotWorkflowAdapterError {
  if (status === 422) return validationError()
  if ([404, 409].includes(status) && isSafeErrorEnvelope(value)) {
    return forwardedPythonError(status as 404 | 409, value.error.code, value.error.message)
  }
  return unavailableError()
}

export function createPythonCategoryApi(
  identity: ServerIdentity,
  options: PythonApiClientOptions = {}
) {
  const { client, responseData } = createAuthenticatedPythonTransport(identity, options)
  return {
    list() {
      return responseData(client.GET("/api/v1/categories"), mapError)
    },
    create(payload: CategoryCreate) {
      return responseData(client.POST("/api/v1/categories", { body: payload }), mapError)
    },
    update(categoryId: string, payload: CategoryUpdate) {
      return responseData(
        client.PATCH("/api/v1/categories/{category_id}", {
          params: { path: { category_id: categoryId } },
          body: payload,
        }),
        mapError
      )
    },
    delete(categoryId: string) {
      return responseData(
        client.DELETE("/api/v1/categories/{category_id}", {
          params: { path: { category_id: categoryId } },
        }),
        mapError
      )
    },
  }
}
