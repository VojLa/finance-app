import "server-only"

import type { components } from "@/generated/python-api"
import {
  forwardedPythonError,
  type SnapshotWorkflowAdapterError,
  unavailableError,
} from "@/modules/python-api/server/errors"
import type { ServerIdentity } from "@/modules/python-api/server/internal-token"
import {
  createAuthenticatedPythonTransport,
  isSafeErrorEnvelope,
  type PythonApiClientOptions,
} from "@/modules/python-api/server/transport"

const AUTH_SERVICE_IDENTITY: ServerIdentity = {
  userId: "finance-app-next-auth-service",
}

type AuthenticatedUser = components["schemas"]["AuthenticatedUserResponse"]
type CredentialVerificationRequest = components["schemas"]["CredentialVerificationRequest"]
type UserRegistrationRequest = components["schemas"]["UserRegistrationRequest"]
type PasswordChangeRequest = components["schemas"]["PasswordChangeRequest"]

function mapAuthError(status: number, value: unknown): SnapshotWorkflowAdapterError {
  if ([401, 409, 422].includes(status) && isSafeErrorEnvelope(value)) {
    return forwardedPythonError(status as 401 | 409 | 422, value.error.code, value.error.message)
  }
  return unavailableError()
}

export function createPythonAuthApi(options: PythonApiClientOptions = {}) {
  const serviceTransport = createAuthenticatedPythonTransport(AUTH_SERVICE_IDENTITY, options)

  return {
    verifyCredentials(payload: CredentialVerificationRequest): Promise<AuthenticatedUser> {
      return serviceTransport.responseData(
        serviceTransport.client.POST("/api/v1/auth/credentials/verify", { body: payload }),
        mapAuthError
      )
    },
    register(payload: UserRegistrationRequest): Promise<AuthenticatedUser> {
      return serviceTransport.responseData(
        serviceTransport.client.POST("/api/v1/auth/register", { body: payload }),
        mapAuthError
      )
    },
    changePassword(
      identity: ServerIdentity,
      payload: PasswordChangeRequest
    ): Promise<components["schemas"]["PasswordChangeResponse"]> {
      const userTransport = createAuthenticatedPythonTransport(identity, options)
      return userTransport.responseData(
        userTransport.client.PUT("/api/v1/auth/password", { body: payload }),
        mapAuthError
      )
    },
  }
}
