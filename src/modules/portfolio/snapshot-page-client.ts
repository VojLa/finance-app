import type {
  PortfolioSnapshotData,
  SnapshotRefreshSummary,
} from "@/modules/python-api/snapshot-workflow-contract"

export const PORTFOLIO_WORKFLOW_PATH = "/api/snapshot-workflow/portfolio"

export type PortfolioPageState =
  | { status: "loading" }
  | { status: "empty"; refresh: SnapshotRefreshSummary }
  | { status: "ready"; refresh: SnapshotRefreshSummary; data: PortfolioSnapshotData }
  | { status: "error"; code: string; message: string }

type FetchImplementation = typeof fetch

const UNAVAILABLE_STATE: PortfolioPageState = {
  status: "error",
  code: "python_api_unavailable",
  message: "Portfolio se nepodařilo načíst.",
}

const CONTRACT_STATE: PortfolioPageState = {
  status: "error",
  code: "python_api_contract_error",
  message: "Portfolio API vrátilo nekompatibilní odpověď.",
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isRefreshSummary(value: unknown): value is SnapshotRefreshSummary {
  if (!isRecord(value)) return false
  return (
    typeof value.netWorthSnapshotId === "string" &&
    (value.netWorthStatus === "created" || value.netWorthStatus === "replayed") &&
    typeof value.timestamp === "string" &&
    typeof value.granularity === "string" &&
    typeof value.currency === "string" &&
    typeof value.calculationVersion === "number" &&
    typeof value.refreshAccountCount === "number" &&
    typeof value.reuseOnlyAccountCount === "number" &&
    typeof value.createdAccountSnapshotCount === "number" &&
    typeof value.replayedAccountSnapshotCount === "number" &&
    typeof value.reusedAccountSnapshotCount === "number" &&
    typeof value.selectedAccountSnapshotCount === "number"
  )
}

function isPortfolioData(value: unknown): value is PortfolioSnapshotData {
  return (
    isRecord(value) &&
    typeof value.timestamp === "string" &&
    typeof value.granularity === "string" &&
    typeof value.currency === "string" &&
    typeof value.calculationVersion === "number" &&
    isRecord(value.summary) &&
    Array.isArray(value.accounts) &&
    value.accounts.length > 0
  )
}

function safeErrorState(value: unknown): PortfolioPageState {
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

export async function requestPortfolioPageState(
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<PortfolioPageState> {
  try {
    const response = await fetchImplementation(PORTFOLIO_WORKFLOW_PATH, {
      method: "POST",
      cache: "no-store",
    })
    const payload: unknown = await response.json()

    if (!response.ok) return safeErrorState(payload)
    if (!isRecord(payload) || !isRefreshSummary(payload.refresh)) return CONTRACT_STATE
    if (payload.status === "empty" && !("data" in payload)) {
      return { status: "empty", refresh: payload.refresh }
    }
    if (payload.status === "ready" && isPortfolioData(payload.data)) {
      return {
        status: "ready",
        refresh: payload.refresh,
        data: payload.data,
      }
    }
    return CONTRACT_STATE
  } catch {
    return UNAVAILABLE_STATE
  }
}
