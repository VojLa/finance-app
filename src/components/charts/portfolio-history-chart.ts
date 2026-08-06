import type {
  SnapshotPortfolioHistoryPoint,
  SnapshotPortfolioHistoryRange,
} from "@/modules/portfolio/snapshot-history-contract"

export type PortfolioHistoryValueMode = "netWorth" | "investments"

export type PortfolioHistoryChartProps = Readonly<{
  points: readonly SnapshotPortfolioHistoryPoint[]
  currency: string
  range: SnapshotPortfolioHistoryRange
  onRangeChange: (range: SnapshotPortfolioHistoryRange) => void
  valueMode: PortfolioHistoryValueMode
  onValueModeChange: (mode: PortfolioHistoryValueMode) => void
}>

export type PortfolioHistoryChartPoint = Readonly<{
  timestamp: string
  exactValue: string
  displayValue: number
  dateLabel: string
}>

function dateLabel(timestamp: string): string {
  return new Date(`${timestamp}Z`).toLocaleDateString("cs-CZ", {
    day: "numeric",
    month: "short",
    year: "numeric",
  })
}

export function buildPortfolioHistoryChartPoints(
  points: readonly SnapshotPortfolioHistoryPoint[],
  valueMode: PortfolioHistoryValueMode
): PortfolioHistoryChartPoint[] {
  return points.map((point) => {
    const exactValue = valueMode === "netWorth" ? point.netWorthValue : point.investmentValue
    return {
      timestamp: point.timestamp,
      exactValue,
      // Presentation-only conversion at the Recharts coordinate leaf boundary.
      displayValue: Number(exactValue),
      dateLabel: dateLabel(point.timestamp),
    }
  })
}
