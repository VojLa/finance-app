import type { Budget, BudgetSaveRequest } from "./budget-contract"

export const BUDGET_PATH = "/api/budget"

export class BudgetClientError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "BudgetClientError"
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
        : "Rozpočet je dočasně nedostupný."
    throw new BudgetClientError(message)
  }
  return value as T
}

export async function requestBudget(
  month: number,
  year: number,
  fetcher: typeof fetch = fetch
): Promise<Budget | null> {
  const query = new URLSearchParams({ month: String(month), year: String(year) })
  return responseJson<Budget | null>(
    await fetcher(`${BUDGET_PATH}?${query}`, { cache: "no-store" })
  )
}

export async function saveBudget(
  payload: BudgetSaveRequest,
  fetcher: typeof fetch = fetch
): Promise<Budget> {
  return responseJson<Budget>(
    await fetcher(BUDGET_PATH, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    })
  )
}
