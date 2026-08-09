import type {
  CurrentValueSummary,
  DashboardSnapshotData,
} from "@/modules/python-api/snapshot-workflow-contract"

export const DASHBOARD_WORKFLOW_PATH = "/api/snapshot-workflow/dashboard"

export type DashboardFinancialState =
  | { status: "loading" }
  | { status: "ready"; current: CurrentValueSummary; data: DashboardSnapshotData }
  | { status: "error"; code: string; message: string }

type FetchImplementation = typeof fetch

const UNAVAILABLE_STATE: DashboardFinancialState = {
  status: "error",
  code: "python_api_unavailable",
  message: "Finanční přehled se nepodařilo načíst.",
}

const CONTRACT_STATE: DashboardFinancialState = {
  status: "error",
  code: "python_api_contract_error",
  message: "Dashboard API vrátilo nekompatibilní odpověď.",
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isCurrentSummary(value: unknown): value is CurrentValueSummary {
  if (!isRecord(value)) return false
  return (
    typeof value.asOf === "string" &&
    typeof value.baselineTimestamp === "string" &&
    typeof value.historyAnchorSnapshotId === "string" &&
    typeof value.currency === "string" &&
    typeof value.calculationVersion === "number" &&
    value.calculationVersion > 0
  )
}

function isDashboardSnapshotData(value: unknown): value is DashboardSnapshotData {
  return (
    isRecord(value) &&
    typeof value.asOf === "string" &&
    typeof value.currency === "string" &&
    typeof value.calculationVersion === "number" &&
    isRecord(value.summary) &&
    Array.isArray(value.accounts) &&
    value.accounts.length > 0 &&
    Array.isArray(value.assetTypeAllocations) &&
    Array.isArray(value.topPositions)
  )
}

function safeErrorState(value: unknown): DashboardFinancialState {
  if (!isRecord(value) || !isRecord(value.error)) return UNAVAILABLE_STATE
  if (typeof value.error.code !== "string" || typeof value.error.message !== "string") {
    return UNAVAILABLE_STATE
  }
  return {
    status: "error",
    code: value.error.code,
    message: value.error.message,
  }
}

export async function requestDashboardFinancialState(
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<DashboardFinancialState> {
  try {
    const response = await fetchImplementation(DASHBOARD_WORKFLOW_PATH, {
      method: "POST",
      cache: "no-store",
    })
    const payload: unknown = await response.json()

    if (!response.ok) return safeErrorState(payload)
    if (!isRecord(payload) || !isCurrentSummary(payload.current)) return CONTRACT_STATE
    if (payload.status === "ready" && isDashboardSnapshotData(payload.data)) {
      return {
        status: "ready",
        current: payload.current,
        data: payload.data,
      }
    }
    return CONTRACT_STATE
  } catch {
    return UNAVAILABLE_STATE
  }
}
