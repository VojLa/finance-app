import type { components } from "@/generated/python-api"

export type PythonSnapshotRefreshResponse =
  components["schemas"]["UserSnapshotRefreshRecalculateResponse"]
export type ExactPortfolioSnapshotManifest =
  components["schemas"]["ExactPortfolioSnapshotSetRequest"]
export type PortfolioSnapshotData = components["schemas"]["MultiAccountPortfolioResponse"]
export type DashboardSnapshotData = components["schemas"]["DashboardSnapshotResponse"]

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

export type EmptySnapshotWorkflowResult = {
  status: "empty"
  refresh: SnapshotRefreshSummary
}

export type ReadySnapshotWorkflowResult<T> = {
  status: "ready"
  refresh: SnapshotRefreshSummary
  data: T
}

export type SnapshotWorkflowResult<T> = EmptySnapshotWorkflowResult | ReadySnapshotWorkflowResult<T>

export type SnapshotWorkflowErrorResponse = {
  error: {
    code: string
    message: string
  }
}
