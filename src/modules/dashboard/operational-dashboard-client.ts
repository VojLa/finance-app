import type { OperationalDashboardData } from "./operational-dashboard-contract"
import { buildOperationalDashboardData } from "./operational-dashboard-model"

export const OPERATIONAL_DASHBOARD_PATH = "/api/dashboard"

export type DashboardOperationalState =
  | { status: "loading" }
  | { status: "ready"; data: OperationalDashboardData }
  | { status: "error"; message: string }

type FetchImplementation = typeof fetch

const ERROR_STATE: DashboardOperationalState = {
  status: "error",
  message: "Provozní přehled se nepodařilo načíst.",
}

export async function requestOperationalDashboardState(
  fetchImplementation: FetchImplementation = globalThis.fetch
): Promise<DashboardOperationalState> {
  try {
    const response = await fetchImplementation(OPERATIONAL_DASHBOARD_PATH, {
      method: "GET",
      cache: "no-store",
    })
    if (!response.ok) return ERROR_STATE
    const payload: unknown = await response.json()
    return {
      status: "ready",
      data: buildOperationalDashboardData(payload),
    }
  } catch {
    return ERROR_STATE
  }
}
