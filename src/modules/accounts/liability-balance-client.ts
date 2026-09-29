import type {
  CreateManualLiabilityBalanceRequest,
  LiabilityBalanceApiErrorResponse,
  ManualLiabilityBalanceResponse,
} from "./liability-balance-contract"
import {
  isLiabilityBalanceApiErrorResponse,
  parseManualLiabilityBalanceResponse,
} from "./liability-balance-contract"

export class LiabilityBalanceClientError extends Error {
  readonly code: string
  readonly status: number

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = "LiabilityBalanceClientError"
    this.status = status
    this.code = code
  }
}

function unavailableError(): LiabilityBalanceClientError {
  return new LiabilityBalanceClientError(
    502,
    "python_api_unavailable",
    "Zůstatek dluhu se nepodařilo uložit."
  )
}

function contractError(): LiabilityBalanceClientError {
  return new LiabilityBalanceClientError(
    502,
    "python_api_contract_error",
    "Služba zůstatků dluhu vrátila nekompatibilní odpověď."
  )
}

export async function requestCreateManualLiabilityBalance(
  accountId: string,
  payload: CreateManualLiabilityBalanceRequest,
  fetchImplementation: typeof fetch = globalThis.fetch
): Promise<ManualLiabilityBalanceResponse> {
  try {
    const response = await fetchImplementation(
      `/api/accounts/${encodeURIComponent(accountId)}/liability-balances`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        cache: "no-store",
      }
    )
    if (!response.headers.get("content-type")?.toLowerCase().includes("json")) {
      throw unavailableError()
    }
    const value: unknown = await response.json()
    if (!response.ok) {
      if (isLiabilityBalanceApiErrorResponse(value)) {
        throw new LiabilityBalanceClientError(
          response.status,
          value.error.code,
          value.error.message
        )
      }
      throw unavailableError()
    }
    try {
      return parseManualLiabilityBalanceResponse(value)
    } catch {
      throw contractError()
    }
  } catch (error) {
    if (error instanceof LiabilityBalanceClientError) {
      throw error
    }
    throw unavailableError()
  }
}

export function toLiabilityBalanceErrorResponse(
  error: LiabilityBalanceClientError
): LiabilityBalanceApiErrorResponse {
  return { error: { code: error.code, message: error.message } }
}
