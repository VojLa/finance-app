import { readFile } from "node:fs/promises"
import path from "node:path"

import { getServerSession } from "next-auth"
import { NextRequest } from "next/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { forwardedPythonError, unavailableError } from "@/modules/python-api/server/errors"
import { readSnapshotBackedPortfolioHistory } from "@/modules/python-api/server/portfolio-history"
import { GET } from "./route"

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}))

vi.mock("@/lib/auth", () => ({
  authOptions: { providers: [] },
}))

vi.mock("@/modules/python-api/server/portfolio-history", () => ({
  readSnapshotBackedPortfolioHistory: vi.fn(),
}))

const getSession = vi.mocked(getServerSession)
const readHistory = vi.mocked(readSnapshotBackedPortfolioHistory)
const HISTORY = {
  range: "1Y" as const,
  currency: "EUR",
  points: [
    {
      timestamp: "2036-01-01T00:00:00.000",
      cashValue: "10.000000",
      investmentValue: "20.000000",
      liabilitiesValue: "5.000000",
      netWorthValue: "25.000000",
    },
  ],
}

function request(query = ""): NextRequest {
  return new NextRequest(`http://next.test/api/portfolio/history${query}`, {
    method: "GET",
    headers: {
      Authorization: "browser-token",
      Cookie: "next-auth=session-cookie",
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  getSession.mockResolvedValue({
    user: { id: "user-1", email: "user@example.test" },
    expires: "2036-01-01",
  })
  readHistory.mockResolvedValue(HISTORY)
})

describe("portfolio history route", () => {
  it("rejects a missing or blank session before Python", async () => {
    getSession.mockResolvedValueOnce(null)
    const missing = await GET(request())
    getSession.mockResolvedValueOnce({
      user: { id: " ", email: "user@example.test" },
      expires: "2036-01-01",
    })
    const blank = await GET(request())

    expect(missing.status).toBe(401)
    expect(blank.status).toBe(401)
    expect(await missing.json()).toEqual({
      error: {
        code: "authentication_required",
        message: "Authentication is required.",
      },
    })
    expect(readHistory).not.toHaveBeenCalled()
  })

  it("uses the default range and verified identity exactly once", async () => {
    const response = await GET(request())

    expect(readHistory).toHaveBeenCalledTimes(1)
    expect(readHistory).toHaveBeenCalledWith({ userId: "user-1", email: "user@example.test" }, "1Y")
    expect(response.headers.get("Cache-Control")).toBe("no-store")
    expect(await response.json()).toEqual(HISTORY)
  })

  it.each(["1W", "1M", "3M", "6M", "1Y", "ALL"] as const)(
    "forwards the exact %s range",
    async (range) => {
      readHistory.mockResolvedValue({ ...HISTORY, range })

      await GET(request(`?range=${range}`))

      expect(readHistory).toHaveBeenCalledTimes(1)
      expect(readHistory).toHaveBeenCalledWith(
        { userId: "user-1", email: "user@example.test" },
        range
      )
    }
  )

  it.each([
    "?range=YEAR",
    "?range=",
    "?accountId=account-1",
    "?userId=user-2",
    "?currency=EUR",
    "?from=2036-01-01",
    "?to=2036-02-01",
    "?granularity=day",
    "?range=1Y&limit=10",
    "?range=1Y&range=1M",
  ])("rejects invalid or additional query contract %s", async (query) => {
    const response = await GET(request(query))

    expect(response.status).toBe(422)
    expect(await response.json()).toEqual({
      error: {
        code: "validation_error",
        message: "Request validation failed.",
      },
    })
    expect(readHistory).not.toHaveBeenCalled()
  })

  it("forwards only the exact Python success body", async () => {
    const response = await GET(request("?range=1Y"))

    expect(response.status).toBe(200)
    expect(JSON.stringify([...response.headers])).not.toMatch(/browser-token|session-cookie/)
    expect(await response.json()).toEqual(HISTORY)
  })

  it("maps the safe Python unavailable conflict without raw details", async () => {
    readHistory.mockRejectedValue(
      forwardedPythonError(
        409,
        "portfolio_history_unavailable",
        "Portfolio history is unavailable."
      )
    )

    const response = await GET(request())

    expect(response.status).toBe(409)
    expect(await response.json()).toEqual({
      error: {
        code: "portfolio_history_unavailable",
        message: "Portfolio history is unavailable.",
      },
    })
  })

  it("maps transport failures to stable unavailable without retry", async () => {
    readHistory.mockRejectedValue(unavailableError())

    const response = await GET(request())

    expect(readHistory).toHaveBeenCalledTimes(1)
    expect(response.status).toBe(502)
    expect(await response.json()).toEqual({
      error: {
        code: "python_api_unavailable",
        message: "The Python API is unavailable.",
      },
    })
  })

  it("contains no legacy production dependency", async () => {
    const source = await readFile(
      path.join(process.cwd(), "src/app/api/portfolio/history/route.ts"),
      "utf8"
    )

    expect(source).toContain("readSnapshotBackedPortfolioHistory")
    expect(source).not.toMatch(
      /@\/modules\/snapshots|@\/lib\/accountAccess|@\/lib\/prisma|portfolio\/rates|getPortfolioSnapshotHistory/
    )
  })
})
