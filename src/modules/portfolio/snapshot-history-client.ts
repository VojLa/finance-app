import type {
  PortfolioChartDataPoint,
  PortfolioChartRange,
} from "@/components/charts/PortfolioLineChart"

type FetchImplementation = typeof fetch

// History cutover is intentionally outside 5M-C. This legacy response is chart-only
// and must never supply current cards, positions, account options, allocation, or currency.
export async function requestPortfolioHistory(
  range: PortfolioChartRange,
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<PortfolioChartDataPoint[]> {
  try {
    const parameters = new URLSearchParams({ range })
    const response = await fetchImplementation(`/api/portfolio/history?${parameters.toString()}`, {
      cache: "no-store",
    })
    if (!response.ok) return []
    const payload: unknown = await response.json()
    return Array.isArray(payload) ? (payload as PortfolioChartDataPoint[]) : []
  } catch {
    return []
  }
}
