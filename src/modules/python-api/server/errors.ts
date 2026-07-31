import "server-only"

import type { SnapshotWorkflowErrorResponse } from "../snapshot-workflow-contract"

type AdapterErrorDefinition = {
  status: number
  code: string
  message: string
}

const CONFIGURATION_ERROR: AdapterErrorDefinition = {
  status: 503,
  code: "python_api_configuration_error",
  message: "The Python API adapter is not configured.",
}

const UNAVAILABLE_ERROR: AdapterErrorDefinition = {
  status: 502,
  code: "python_api_unavailable",
  message: "The Python API is unavailable.",
}

const CONTRACT_ERROR: AdapterErrorDefinition = {
  status: 502,
  code: "python_api_contract_error",
  message: "The Python API returned an incompatible response.",
}

export class SnapshotWorkflowAdapterError extends Error {
  readonly status: number
  readonly code: string

  constructor(definition: AdapterErrorDefinition) {
    super(definition.message)
    this.name = "SnapshotWorkflowAdapterError"
    this.status = definition.status
    this.code = definition.code
  }
}

export function configurationError(): SnapshotWorkflowAdapterError {
  return new SnapshotWorkflowAdapterError(CONFIGURATION_ERROR)
}

export function unavailableError(): SnapshotWorkflowAdapterError {
  return new SnapshotWorkflowAdapterError(UNAVAILABLE_ERROR)
}

export function contractError(): SnapshotWorkflowAdapterError {
  return new SnapshotWorkflowAdapterError(CONTRACT_ERROR)
}

export function forwardedPythonError(
  status: 404 | 409,
  code: string,
  message: string
): SnapshotWorkflowAdapterError {
  return new SnapshotWorkflowAdapterError({ status, code, message })
}

export function normalizeAdapterError(error: unknown): SnapshotWorkflowAdapterError {
  return error instanceof SnapshotWorkflowAdapterError ? error : unavailableError()
}

export function toErrorResponse(error: SnapshotWorkflowAdapterError): {
  status: number
  body: SnapshotWorkflowErrorResponse
} {
  return {
    status: error.status,
    body: {
      error: {
        code: error.code,
        message: error.message,
      },
    },
  }
}
