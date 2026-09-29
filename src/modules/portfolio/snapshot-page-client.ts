import type {
  CurrentValueSummary,
  PortfolioSnapshotData,
} from "@/modules/python-api/snapshot-workflow-contract"

export const PORTFOLIO_WORKFLOW_PATH = "/api/snapshot-workflow/portfolio"
export const PORTFOLIO_REFRESH_WORKFLOW_PATH = "/api/snapshot-workflow/portfolio/refresh"

export type PortfolioPageState =
  | { status: "loading" }
  | { status: "ready"; current: CurrentValueSummary; data: PortfolioSnapshotData }
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

function isCurrentSummary(value: unknown): value is CurrentValueSummary {
  if (!isRecord(value)) return false
  return (
    typeof value.asOf === "string" &&
    typeof value.baselineTimestamp === "string" &&
    typeof value.historyAnchorSnapshotId === "string" &&
    typeof value.valuationTimestamp === "string" &&
    typeof value.isStale === "boolean" &&
    typeof value.currency === "string" &&
    typeof value.calculationVersion === "number" &&
    value.calculationVersion > 0
  )
}

function isPortfolioData(value: unknown): value is PortfolioSnapshotData {
  return (
    isRecord(value) &&
    typeof value.asOf === "string" &&
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
  fetchImplementation: FetchImplementation = globalThis.fetch,
  refresh = false
): Promise<PortfolioPageState> {
  try {
    const response = await fetchImplementation(
      refresh ? PORTFOLIO_REFRESH_WORKFLOW_PATH : PORTFOLIO_WORKFLOW_PATH,
      {
      method: "POST",
      cache: "no-store",
      }
    )
    const payload: unknown = await response.json()

    if (!response.ok) return safeErrorState(payload)
    if (!isRecord(payload) || !isCurrentSummary(payload.current)) return CONTRACT_STATE
    if (payload.status === "ready" && isPortfolioData(payload.data)) {
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
