import type { components } from "@/generated/python-api"

export type PythonSnapshotRefreshResponse =
  components["schemas"]["UserSnapshotRefreshRecalculateResponse"]
export type ExactPortfolioSnapshotManifest =
  components["schemas"]["ExactPortfolioSnapshotSetRequest"]
export type LegacyPortfolioSnapshotData = components["schemas"]["MultiAccountPortfolioResponse"]
export type LegacyDashboardSnapshotData = components["schemas"]["DashboardSnapshotResponse"]
export type PortfolioSnapshotData = components["schemas"]["CurrentPortfolioResponse"]
export type DashboardSnapshotData = components["schemas"]["CurrentDashboardResponse"]

export type SnapshotRefreshSummary = {
  netWorthSnapshotId: string
  netWorthStatus: "created" | "replayed"
  timestamp: string
  granularity: string
  currency: string
  calculationVersion: number
  refreshAccountCount: number
  reuseOnlyAccountCount: number
  createdAccountSnapshotCount: number
  replayedAccountSnapshotCount: number
  reusedAccountSnapshotCount: number
  selectedAccountSnapshotCount: number
}

export type CurrentValueSummary = {
  asOf: string
  baselineTimestamp: string
  historyAnchorSnapshotId: string
  currency: string
  calculationVersion: number
}

export type ReadySnapshotWorkflowResult<T> = {
  status: "ready"
  current: CurrentValueSummary
  data: T
}

export type SnapshotWorkflowResult<T> = ReadySnapshotWorkflowResult<T>

export type SnapshotWorkflowErrorResponse = {
  error: {
    code: string
    message: string
  }
}
