import type {
  SnapshotPortfolioHistoryCoverage,
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
  preferredResolutionMinutes: number | undefined
  resolutions: readonly number[]
  coverage: readonly SnapshotPortfolioHistoryCoverage[]
  onPointSelect?: (point: SnapshotPortfolioHistoryPoint) => void
}>

export type PortfolioHistoryChartPoint = Readonly<{
  timestamp: string
  exactValue: string
  displayValue: number
  dateLabel: string
  resolutionMinutes: number
  resolutionLabel: string
  netInvestedExactValue: string | null
  netInvestedDisplayValue: number | null
  source: SnapshotPortfolioHistoryPoint
}>

function dateLabel(timestamp: string): string {
  return new Date(`${timestamp}Z`).toLocaleString("cs-CZ", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function formatHistoryResolution(resolutionMinutes: number): string {
  if (resolutionMinutes % 1_440 === 0) return `${resolutionMinutes / 1_440} d`
  if (resolutionMinutes % 60 === 0) return `${resolutionMinutes / 60} h`
  return `${resolutionMinutes} min`
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
      resolutionMinutes: point.resolutionMinutes,
      resolutionLabel: formatHistoryResolution(point.resolutionMinutes),
      netInvestedExactValue: point.netInvestedValue ?? null,
      netInvestedDisplayValue:
        point.netInvestedValue === undefined ? null : Number(point.netInvestedValue),
      source: point,
    }
  })
}
