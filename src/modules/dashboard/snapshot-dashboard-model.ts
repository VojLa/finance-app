import type { DashboardSnapshotData } from "@/modules/python-api/snapshot-workflow-contract"

export type SnapshotDashboardModel = Readonly<{
  timestamp: string
  granularity: string
  calculationVersion: number
  currency: string
  summary: DashboardSnapshotData["summary"]
  accounts: DashboardSnapshotData["accounts"]
  assetTypeAllocations: DashboardSnapshotData["assetTypeAllocations"]
  topPositions: DashboardSnapshotData["topPositions"]
}>

export function buildSnapshotDashboardModel(data: DashboardSnapshotData): SnapshotDashboardModel {
  return {
    timestamp: data.asOf,
    granularity: "current",
    calculationVersion: data.calculationVersion,
    currency: data.currency,
    summary: data.summary,
    accounts: data.accounts,
    assetTypeAllocations: data.assetTypeAllocations,
    topPositions: data.topPositions,
  }
}
