import type {
  ManualInvestmentCreateRequest,
  ManualInvestmentCreateResponse,
  SymbolDetail,
} from "./investment-contract"

export const INVESTMENT_PATH = "/api/portfolio/transactions"

export class InvestmentClientError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "InvestmentClientError"
  }
}

async function responseJson<T>(response: Response): Promise<T> {
  const value = (await response.json()) as T | { error?: unknown }
  if (!response.ok) {
    const message =
      typeof value === "object" &&
      value !== null &&
      "error" in value &&
      typeof value.error === "string"
        ? value.error
        : "Investiční operace je dočasně nedostupná."
    throw new InvestmentClientError(message)
  }
  return value as T
}

export async function createManualInvestment(
  payload: ManualInvestmentCreateRequest,
  fetcher: typeof fetch = fetch
): Promise<ManualInvestmentCreateResponse> {
  return responseJson<ManualInvestmentCreateResponse>(
    await fetcher(INVESTMENT_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    })
  )
}

export async function requestSymbolDetail(
  symbol: string,
  fetcher: typeof fetch = fetch
): Promise<SymbolDetail> {
  const query = new URLSearchParams({ symbol })
  return responseJson<SymbolDetail>(
    await fetcher(`${INVESTMENT_PATH}?${query}`, { cache: "no-store" })
  )
}
