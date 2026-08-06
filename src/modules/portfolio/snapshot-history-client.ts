import {
  parseSnapshotPortfolioHistory,
  type SnapshotPortfolioHistoryRange,
  type SnapshotPortfolioHistoryResponse,
} from "./snapshot-history-contract"

type FetchImplementation = typeof fetch

export type PortfolioHistoryLoadResult =
  | Readonly<{
      status: "ready"
      data: SnapshotPortfolioHistoryResponse
    }>
  | Readonly<{
      status: "empty"
      data: SnapshotPortfolioHistoryResponse
    }>
  | Readonly<{
      status: "error"
      message: string
    }>

const HISTORY_ERROR_MESSAGE = "Historii portfolia se nepodařilo načíst."

export async function requestPortfolioHistory(
  range: SnapshotPortfolioHistoryRange,
  expectedCurrency: string,
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<PortfolioHistoryLoadResult> {
  try {
    const parameters = new URLSearchParams({ range })
    const response = await fetchImplementation(`/api/portfolio/history?${parameters.toString()}`, {
      method: "GET",
      cache: "no-store",
    })
    if (!response.ok) {
      return { status: "error", message: HISTORY_ERROR_MESSAGE }
    }
    const payload: unknown = await response.json()
    const data = parseSnapshotPortfolioHistory(payload, range, expectedCurrency)
    return data.points.length === 0 ? { status: "empty", data } : { status: "ready", data }
  } catch {
    return { status: "error", message: HISTORY_ERROR_MESSAGE }
  }
}

export function startPortfolioHistoryRequest(
  range: SnapshotPortfolioHistoryRange,
  expectedCurrency: string,
  onResult: (result: PortfolioHistoryLoadResult) => void,
  fetchImplementation: FetchImplementation = globalThis.fetch
): () => void {
  let active = true
  void requestPortfolioHistory(range, expectedCurrency, fetchImplementation).then((result) => {
    if (active) onResult(result)
  })
  return () => {
    active = false
  }
}
