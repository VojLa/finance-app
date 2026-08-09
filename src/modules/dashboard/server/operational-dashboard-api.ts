import "server-only"

import type { ServerIdentity } from "@/modules/python-api/server/internal-token"
import {
  forwardedPythonError,
  type SnapshotWorkflowAdapterError,
  unavailableError,
} from "@/modules/python-api/server/errors"
import {
  createAuthenticatedPythonTransport,
  isSafeErrorEnvelope,
  type PythonApiClientOptions,
} from "@/modules/python-api/server/transport"

function mapError(status: number, value: unknown): SnapshotWorkflowAdapterError {
  if (status === 409 && isSafeErrorEnvelope(value)) {
    return forwardedPythonError(409, value.error.code, value.error.message)
  }
  return unavailableError()
}

export function createPythonOperationalDashboardApi(
  identity: ServerIdentity,
  options: PythonApiClientOptions = {}
) {
  const { client, responseData } = createAuthenticatedPythonTransport(identity, options)
  return {
    get() {
      return responseData(client.GET("/api/v1/operational-dashboard"), mapError)
    },
  }
}
