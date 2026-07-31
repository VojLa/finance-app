import { getServerSession } from "next-auth"
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest"

import { configurationError, forwardedPythonError } from "@/modules/python-api/server/errors"
import {
  runDashboardSnapshotWorkflow,
  runPortfolioSnapshotWorkflow,
} from "@/modules/python-api/server/snapshot-workflow"
import * as dashboardRoute from "./dashboard/route"
import * as portfolioRoute from "./portfolio/route"

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}))

vi.mock("@/lib/auth", () => ({
  authOptions: { providers: [] },
}))

vi.mock("@/modules/python-api/server/snapshot-workflow", () => ({
  runPortfolioSnapshotWorkflow: vi.fn(),
  runDashboardSnapshotWorkflow: vi.fn(),
}))

const getSession = vi.mocked(getServerSession)
const runPortfolio = vi.mocked(runPortfolioSnapshotWorkflow)
const runDashboard = vi.mocked(runDashboardSnapshotWorkflow)

const READY_RESULT = {
  status: "ready" as const,
  refresh: {
    netWorthSnapshotId: "net-worth-1",
    netWorthStatus: "created" as const,
    timestamp: "2036-01-02T03:04:00.000",
    granularity: "minute",
    currency: "EUR",
    calculationVersion: 1,
    refreshAccountCount: 1,
    reuseOnlyAccountCount: 0,
    createdAccountSnapshotCount: 1,
    replayedAccountSnapshotCount: 0,
    reusedAccountSnapshotCount: 0,
    selectedAccountSnapshotCount: 1,
  },
  data: {
    timestamp: "2036-01-02T03:04:00.000",
    granularity: "minute",
    currency: "EUR",
    calculationVersion: 1,
    summary: { totalValue: "10.000001" },
    accounts: [],
  },
}

const EMPTY_RESULT = {
  status: "empty" as const,
  refresh: {
    ...READY_RESULT.refresh,
    refreshAccountCount: 0,
    createdAccountSnapshotCount: 0,
    selectedAccountSnapshotCount: 0,
  },
}

type RouteCase = {
  name: string
  post: () => Promise<Response>
  workflow: Mock
  otherWorkflow: Mock
  module: Record<string, unknown>
}

const ROUTES: RouteCase[] = [
  {
    name: "portfolio",
    post: portfolioRoute.POST,
    workflow: runPortfolio as unknown as Mock,
    otherWorkflow: runDashboard as unknown as Mock,
    module: portfolioRoute,
  },
  {
    name: "dashboard",
    post: dashboardRoute.POST,
    workflow: runDashboard as unknown as Mock,
    otherWorkflow: runPortfolio as unknown as Mock,
    module: dashboardRoute,
  },
]

beforeEach(() => {
  vi.clearAllMocks()
})

describe.each(ROUTES)(
  "$name snapshot workflow route",
  ({ post, workflow, otherWorkflow, module }) => {
    it("exports only POST", () => {
      expect(Object.keys(module)).toEqual(["POST"])
    })

    it("returns stable 401 for a missing session and calls getServerSession once", async () => {
      getSession.mockResolvedValue(null)

      const response = await post()

      expect(getSession).toHaveBeenCalledTimes(1)
      expect(workflow).not.toHaveBeenCalled()
      expect(response.status).toBe(401)
      expect(response.headers.get("Cache-Control")).toBe("no-store")
      expect(await response.json()).toEqual({
        error: {
          code: "authentication_required",
          message: "Authentication is required.",
        },
      })
    })

    it("returns stable 401 for a missing session.user.id", async () => {
      getSession.mockResolvedValue({
        user: { id: " ", email: "user@example.test" },
        expires: "2036-01-01",
      })

      const response = await post()

      expect(getSession).toHaveBeenCalledTimes(1)
      expect(workflow).not.toHaveBeenCalled()
      expect(response.status).toBe(401)
    })

    it.each([
      ["ready", READY_RESULT],
      ["empty", EMPTY_RESULT],
    ] as const)(
      "calls its workflow exactly once and returns the exact %s response",
      async (_status, result) => {
        getSession.mockResolvedValue({
          user: { id: "user-1", email: "user@example.test" },
          expires: "2036-01-01",
        })
        workflow.mockResolvedValue(result as never)

        const response = await post()

        expect(getSession).toHaveBeenCalledTimes(1)
        expect(workflow).toHaveBeenCalledTimes(1)
        expect(workflow).toHaveBeenCalledWith({
          userId: "user-1",
          email: "user@example.test",
        })
        expect(otherWorkflow).not.toHaveBeenCalled()
        expect(response.status).toBe(200)
        expect(response.headers.get("Cache-Control")).toBe("no-store")
        expect(await response.json()).toEqual(result)
      }
    )

    it("ignores a caller body and selector fields", async () => {
      getSession.mockResolvedValue({
        user: { id: "user-1", email: "user@example.test" },
        expires: "2036-01-01",
      })
      workflow.mockResolvedValue(EMPTY_RESULT as never)
      const callerRequest = new Request("http://localhost/api/snapshot-workflow/test", {
        method: "POST",
        headers: {
          Authorization: "browser-token",
          Cookie: "next-auth=session-cookie",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          accountId: "caller-account",
          snapshotId: "caller-snapshot",
          currency: "USD",
        }),
      })

      const response = await (post as unknown as (request: Request) => Promise<Response>)(
        callerRequest
      )

      expect(workflow).toHaveBeenCalledTimes(1)
      expect(workflow).toHaveBeenCalledWith({
        userId: "user-1",
        email: "user@example.test",
      })
      expect(await response.json()).toEqual(EMPTY_RESULT)
    })

    it("maps configuration errors without leaking details", async () => {
      getSession.mockResolvedValue({
        user: { id: "user-1", email: "user@example.test" },
        expires: "2036-01-01",
      })
      workflow.mockRejectedValue(configurationError())

      const response = await post()

      expect(response.status).toBe(503)
      expect(await response.json()).toEqual({
        error: {
          code: "python_api_configuration_error",
          message: "The Python API adapter is not configured.",
        },
      })
    })

    it("forwards safe Python 409 errors and removes request metadata", async () => {
      getSession.mockResolvedValue({
        user: { id: "user-1", email: "user@example.test" },
        expires: "2036-01-01",
      })
      workflow.mockRejectedValue(
        forwardedPythonError(409, "snapshot_refresh_unavailable", "Snapshot unavailable.")
      )

      const response = await post()

      expect(response.status).toBe(409)
      expect(await response.json()).toEqual({
        error: {
          code: "snapshot_refresh_unavailable",
          message: "Snapshot unavailable.",
        },
      })
    })

    it("maps unknown failures to a generic safe 502", async () => {
      getSession.mockResolvedValue({
        user: { id: "user-1", email: "user@example.test" },
        expires: "2036-01-01",
      })
      workflow.mockRejectedValue(new Error("secret traceback and token"))

      const response = await post()

      expect(response.status).toBe(502)
      expect(response.headers.get("Cache-Control")).toBe("no-store")
      expect(await response.json()).toEqual({
        error: {
          code: "python_api_unavailable",
          message: "The Python API is unavailable.",
        },
      })
    })
  }
)
