import "server-only"

import type { CreateAccountRequest, PythonAccount, UpdateAccountRequest } from "../account-contract"
import { parsePythonAccount, parsePythonAccountList } from "../account-contract"
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

function mapAccountPythonError(status: number, value: unknown): SnapshotWorkflowAdapterError {
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

function requireAccount(value: unknown): PythonAccount {
  try {
    return parsePythonAccount(value)
  } catch {
    throw contractError()
  }
}

export function createPythonAccountApi(
  identity: ServerIdentity,
  options: PythonApiClientOptions = {}
) {
  const { client, responseData } = createAuthenticatedPythonTransport(identity, options)

  return {
    async listAccounts(): Promise<PythonAccount[]> {
      const value = await responseData(client.GET("/api/v1/accounts"), mapAccountPythonError)
      try {
        return parsePythonAccountList(value)
      } catch {
        throw contractError()
      }
    },
    async createAccount(payload: CreateAccountRequest): Promise<PythonAccount> {
      const value = await responseData(
        client.POST("/api/v1/accounts", { body: payload }),
        mapAccountPythonError
      )
      return requireAccount(value)
    },
    async updateAccount(accountId: string, payload: UpdateAccountRequest): Promise<PythonAccount> {
      const value = await responseData(
        client.PATCH("/api/v1/accounts/{account_id}", {
          params: { path: { account_id: accountId } },
          body: payload,
        }),
        mapAccountPythonError
      )
      return requireAccount(value)
    },
    async archiveAccount(accountId: string): Promise<PythonAccount> {
      const value = await responseData(
        client.POST("/api/v1/accounts/{account_id}/archive", {
          params: { path: { account_id: accountId } },
        }),
        mapAccountPythonError
      )
      return requireAccount(value)
    },
  }
}

export type PythonAccountApi = ReturnType<typeof createPythonAccountApi>

export function listAccounts(
  identity: ServerIdentity,
  options?: PythonApiClientOptions
): Promise<PythonAccount[]> {
  return createPythonAccountApi(identity, options).listAccounts()
}

export function createAccount(
  identity: ServerIdentity,
  payload: CreateAccountRequest,
  options?: PythonApiClientOptions
): Promise<PythonAccount> {
  return createPythonAccountApi(identity, options).createAccount(payload)
}

export function updateAccount(
  identity: ServerIdentity,
  accountId: string,
  payload: UpdateAccountRequest,
  options?: PythonApiClientOptions
): Promise<PythonAccount> {
  return createPythonAccountApi(identity, options).updateAccount(accountId, payload)
}

export function archiveAccount(
  identity: ServerIdentity,
  accountId: string,
  options?: PythonApiClientOptions
): Promise<PythonAccount> {
  return createPythonAccountApi(identity, options).archiveAccount(accountId)
}
