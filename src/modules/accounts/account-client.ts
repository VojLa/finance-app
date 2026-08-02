import type {
  AccountApiErrorResponse,
  CreateAccountRequest,
  PythonAccount,
  UpdateAccountRequest,
} from "./account-contract"
import {
  isAccountApiErrorResponse,
  parsePythonAccount,
  parsePythonAccountList,
} from "./account-contract"

export const ACCOUNTS_PATH = "/api/accounts"

type FetchImplementation = typeof fetch

export class AccountClientError extends Error {
  readonly code: string
  readonly status: number

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = "AccountClientError"
    this.status = status
    this.code = code
  }
}

function unavailableError(): AccountClientError {
  return new AccountClientError(502, "python_api_unavailable", "Účty se nepodařilo načíst.")
}

function contractError(): AccountClientError {
  return new AccountClientError(
    502,
    "python_api_contract_error",
    "Account API vrátilo nekompatibilní odpověď."
  )
}

async function request<T>(
  path: string,
  init: RequestInit,
  parse: (value: unknown) => T,
  fetchImplementation: FetchImplementation
): Promise<T> {
  try {
    const response = await fetchImplementation(path, { ...init, cache: "no-store" })
    if (!response.headers.get("content-type")?.toLowerCase().includes("json")) {
      throw unavailableError()
    }
    const value: unknown = await response.json()
    if (!response.ok) {
      if (isAccountApiErrorResponse(value)) {
        throw new AccountClientError(response.status, value.error.code, value.error.message)
      }
      throw unavailableError()
    }
    try {
      return parse(value)
    } catch {
      throw contractError()
    }
  } catch (error) {
    if (error instanceof AccountClientError) {
      throw error
    }
    throw unavailableError()
  }
}

export function requestAccounts(
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<PythonAccount[]> {
  return request(ACCOUNTS_PATH, { method: "GET" }, parsePythonAccountList, fetchImplementation)
}

export function requestCreateAccount(
  payload: CreateAccountRequest,
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<PythonAccount> {
  return request(
    ACCOUNTS_PATH,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    parsePythonAccount,
    fetchImplementation
  )
}

export function requestUpdateAccount(
  accountId: string,
  payload: UpdateAccountRequest,
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<PythonAccount> {
  return request(
    `${ACCOUNTS_PATH}/${encodeURIComponent(accountId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    parsePythonAccount,
    fetchImplementation
  )
}

export function requestArchiveAccount(
  accountId: string,
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<PythonAccount> {
  return request(
    `${ACCOUNTS_PATH}/${encodeURIComponent(accountId)}/archive`,
    { method: "POST" },
    parsePythonAccount,
    fetchImplementation
  )
}

export function toAccountErrorResponse(error: AccountClientError): AccountApiErrorResponse {
  return { error: { code: error.code, message: error.message } }
}
