import { getServerSession } from "next-auth"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { forwardedPythonError } from "@/modules/python-api/server/errors"
import { refreshPortfolioSnapshotWorkflow } from "@/modules/python-api/server/snapshot-workflow"
import { POST } from "./route"

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}))

vi.mock("@/lib/auth", () => ({
  authOptions: { providers: [] },
}))

vi.mock("@/modules/python-api/server/snapshot-workflow", () => ({
  refreshPortfolioSnapshotWorkflow: vi.fn(),
}))

const getSession = vi.mocked(getServerSession)
const refreshPortfolio = vi.mocked(refreshPortfolioSnapshotWorkflow)

beforeEach(() => {
  vi.clearAllMocks()
})

describe("portfolio refresh workflow route", () => {
  it("requires an authenticated user before refreshing", async () => {
    getSession.mockResolvedValue(null)

    const response = await POST()

    expect(refreshPortfolio).not.toHaveBeenCalled()
    expect(response.status).toBe(401)
  })

  it("refreshes using the server session identity", async () => {
    getSession.mockResolvedValue({
      user: { id: "user-1", email: "user@example.test" },
      expires: "2036-01-01",
    })
    const result = { status: "ready", current: {}, data: {} }
    refreshPortfolio.mockResolvedValue(result as never)

    const response = await POST()

    expect(refreshPortfolio).toHaveBeenCalledWith({
      userId: "user-1",
      email: "user@example.test",
    })
    expect(response.status).toBe(200)
    expect(response.headers.get("Cache-Control")).toBe("no-store")
    expect(await response.json()).toEqual(result)
  })

  it("forwards the safe baseline-state error", async () => {
    getSession.mockResolvedValue({
      user: { id: "user-1", email: "user@example.test" },
      expires: "2036-01-01",
    })
    refreshPortfolio.mockRejectedValue(
      forwardedPythonError(
        409,
        "daily_snapshot_baseline_unavailable",
        "Daily snapshot baseline evidence is unavailable."
      )
    )

    const response = await POST()

    expect(response.status).toBe(409)
    expect(await response.json()).toEqual({
      error: {
        code: "daily_snapshot_baseline_unavailable",
        message: "Daily snapshot baseline evidence is unavailable.",
      },
    })
  })
})
