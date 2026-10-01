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
  onPointPreview?: (point: SnapshotPortfolioHistoryPoint | null) => void
}>

export type PortfolioHistoryInteractionState = Readonly<{
  pinnedPoint: SnapshotPortfolioHistoryPoint | null
  previewPoint: SnapshotPortfolioHistoryPoint | null
}>

export type PortfolioHistoryInteractionAction =
  | Readonly<{ type: "preview"; point: SnapshotPortfolioHistoryPoint }>
  | Readonly<{ type: "leave" }>
  | Readonly<{ type: "reset" }>
  | Readonly<{ type: "toggle-pin"; point: SnapshotPortfolioHistoryPoint }>

export const EMPTY_PORTFOLIO_HISTORY_INTERACTION: PortfolioHistoryInteractionState = {
  pinnedPoint: null,
  previewPoint: null,
}

export function reducePortfolioHistoryInteraction(
  state: PortfolioHistoryInteractionState,
  action: PortfolioHistoryInteractionAction
): PortfolioHistoryInteractionState {
  if (action.type === "reset") return EMPTY_PORTFOLIO_HISTORY_INTERACTION
  if (action.type === "leave") {
    return state.previewPoint === null ? state : { ...state, previewPoint: null }
  }
  if (action.type === "preview") {
    if (state.pinnedPoint !== null || state.previewPoint?.timestamp === action.point.timestamp) {
      return state
    }
    return { ...state, previewPoint: action.point }
  }
  if (state.pinnedPoint !== null) {
    return { pinnedPoint: null, previewPoint: action.point }
  }
  return { pinnedPoint: action.point, previewPoint: null }
}

export function portfolioHistoryInteractionPoint(
  state: PortfolioHistoryInteractionState
): SnapshotPortfolioHistoryPoint | null {
  return state.pinnedPoint ?? state.previewPoint
}

export type PortfolioHistoryChartPoint = Readonly<{
  timestamp: string
  exactValue: string
  displayValue: number
  dateLabel: string
  resolutionMinutes: number
  resolutionLabel: string
  comparisonExactValue: string | null
  comparisonDisplayValue: number | null
  comparisonLabel: "Vložené prostředky" | "Investováno"
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
    const comparisonExactValue =
      valueMode === "netWorth"
        ? (point.netInvestedValue ?? null)
        : (point.investmentCostBasis ?? null)
    return {
      timestamp: point.timestamp,
      exactValue,
      // Presentation-only conversion at the Recharts coordinate leaf boundary.
      displayValue: Number(exactValue),
      dateLabel: dateLabel(point.timestamp),
      resolutionMinutes: point.resolutionMinutes,
      resolutionLabel: formatHistoryResolution(point.resolutionMinutes),
      comparisonExactValue,
      comparisonDisplayValue: comparisonExactValue === null ? null : Number(comparisonExactValue),
      comparisonLabel: valueMode === "netWorth" ? "Vložené prostředky" : "Investováno",
      source: point,
    }
  })
}
