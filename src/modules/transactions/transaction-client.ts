import type {
  Transaction,
  TransactionCreateRequest,
  TransactionPage,
  TransactionUpdateRequest,
} from "./transaction-contract"

export class TransactionClientError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "TransactionClientError"
  }
}

export const TRANSACTIONS_PATH = "/api/transactions"

async function responseJson<T>(response: Response): Promise<T> {
  const value = (await response.json()) as T | { error?: unknown }
  if (!response.ok) {
    const message =
      typeof value === "object" &&
      value !== null &&
      "error" in value &&
      typeof value.error === "string"
        ? value.error
        : "Transakční služba je dočasně nedostupná."
    throw new TransactionClientError(message)
  }
  return value as T
}

export async function requestTransactions(
  params: {
    page: number
    type?: string
    categoryId?: string
    accountId?: string
    q?: string
  },
  fetcher: typeof fetch = fetch
): Promise<TransactionPage> {
  const query = new URLSearchParams({ page: String(params.page) })
  if (params.type) query.set("type", params.type)
  if (params.categoryId) query.set("categoryId", params.categoryId)
  if (params.accountId) query.set("accountId", params.accountId)
  if (params.q) query.set("q", params.q)
  return responseJson<TransactionPage>(
    await fetcher(`${TRANSACTIONS_PATH}?${query}`, { cache: "no-store" })
  )
}

export async function createTransaction(
  payload: TransactionCreateRequest,
  fetcher: typeof fetch = fetch
): Promise<Transaction> {
  return responseJson<Transaction>(
    await fetcher(TRANSACTIONS_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    })
  )
}

export async function updateTransaction(
  transactionId: string,
  payload: TransactionUpdateRequest,
  fetcher: typeof fetch = fetch
): Promise<Transaction> {
  return responseJson<Transaction>(
    await fetcher(TRANSACTIONS_PATH, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: transactionId, ...payload }),
      cache: "no-store",
    })
  )
}

export async function deleteTransaction(
  transactionId: string,
  fetcher: typeof fetch = fetch
): Promise<void> {
  const query = new URLSearchParams({
    id: transactionId,
    idempotencyKey: crypto.randomUUID(),
  })
  await responseJson<{ ok: boolean }>(
    await fetcher(`${TRANSACTIONS_PATH}?${query}`, {
      method: "DELETE",
      cache: "no-store",
    })
  )
}
