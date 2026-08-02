import { execFileSync } from "node:child_process"
import { readdir, readFile } from "node:fs/promises"
import path from "node:path"

import { getServerSession } from "next-auth"
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest"

import {
  runDashboardSnapshotWorkflow,
  runPortfolioSnapshotWorkflow,
} from "@/modules/python-api/server/snapshot-workflow"
import * as dashboardRoute from "@/app/api/snapshot-workflow/dashboard/route"
import * as portfolioRoute from "@/app/api/snapshot-workflow/portfolio/route"

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

const ROOT = process.cwd()
const BASE_SHA = "64d1e151baf90e160b45d86e8d415811f5dc42f1"
const AUDIT_FINAL_SHA = "20db8a8b5466957868b8ec4e61bcde3d4f2cf265"
const AUDIT_FILES = [
  "!docs/01-architecture/01-technical-overview.md",
  "!docs/01-architecture/04-security.md",
  "!docs/03-api/01-conventions.md",
  "!docs/05-decisions/0005-openapi-contracts.md",
  "ChatGPT/audits/5M-final-audit.md",
  "ChatGPT/steps/5M.md",
  "backend/python/tests/support/verify_internal_token_cli.py",
  "backend/python/tests/test_snapshot_application_cutover_final_audit.py",
  "src/app/dashboard/dashboard-snapshot-cutover.test.ts",
  "src/app/portfolio/portfolio-snapshot-cutover.test.ts",
  "src/app/snapshot-cutover-final-audit.test.ts",
  "src/modules/dashboard/dashboard-cutover-final-audit.test.ts",
  "src/modules/portfolio/portfolio-cutover-final-audit.test.ts",
  "src/modules/python-api/snapshot-cutover-final-audit.test.ts",
]
const getSession = vi.mocked(getServerSession)
const runPortfolio = vi.mocked(runPortfolioSnapshotWorkflow)
const runDashboard = vi.mocked(runDashboardSnapshotWorkflow)

const EMPTY_RESULT = {
  status: "empty" as const,
  refresh: {
    netWorthSnapshotId: "net-worth-audit",
    netWorthStatus: "created" as const,
    timestamp: "2037-01-02T03:04:00.000",
    granularity: "minute",
    currency: "EUR",
    calculationVersion: 1,
    refreshAccountCount: 0,
    reuseOnlyAccountCount: 0,
    createdAccountSnapshotCount: 0,
    replayedAccountSnapshotCount: 0,
    reusedAccountSnapshotCount: 0,
    selectedAccountSnapshotCount: 0,
  },
}

type RouteAudit = {
  name: "portfolio" | "dashboard"
  module: Record<string, unknown>
  post: () => Promise<Response>
  workflow: Mock
  source: string
}

const ROUTES: RouteAudit[] = [
  {
    name: "portfolio",
    module: portfolioRoute,
    post: portfolioRoute.POST,
    workflow: runPortfolio as unknown as Mock,
    source: "src/app/api/snapshot-workflow/portfolio/route.ts",
  },
  {
    name: "dashboard",
    module: dashboardRoute,
    post: dashboardRoute.POST,
    workflow: runDashboard as unknown as Mock,
    source: "src/app/api/snapshot-workflow/dashboard/route.ts",
  },
]

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

async function filesBelow(relativeDirectory: string): Promise<string[]> {
  const entries = await readdir(path.join(ROOT, relativeDirectory), { withFileTypes: true })
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const relativePath = path.join(relativeDirectory, entry.name)
      return entry.isDirectory() ? filesBelow(relativePath) : [relativePath]
    })
  )
  return nested.flat()
}

function changedFiles(): string[] {
  const rangeAvailable = [BASE_SHA, AUDIT_FINAL_SHA].every((commit) => {
    try {
      execFileSync("git", ["cat-file", "-e", `${commit}^{commit}`], {
        cwd: ROOT,
        stdio: "ignore",
      })
      return true
    } catch {
      return false
    }
  })
  if (!rangeAvailable) {
    return AUDIT_FILES
  }
  return execFileSync("git", ["diff", "--name-only", BASE_SHA, AUDIT_FINAL_SHA, "--"], {
    cwd: ROOT,
    encoding: "utf8",
  })
    .split(/\r?\n/)
    .filter(Boolean)
    .map((file) => file.replaceAll("\\", "/"))
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe("5M production file freeze", () => {
  it("contains only audit tests, test support, reports, and documentation", () => {
    expect(changedFiles().sort()).toEqual([...AUDIT_FILES].sort())
  })
})

describe.each(ROUTES)(
  "$name workflow route final audit",
  ({ module, post, workflow, source: file }) => {
    it("is one of exactly two POST-only bodyless route modules", async () => {
      const routeFiles = (await filesBelow("src/app/api/snapshot-workflow"))
        .filter((candidate) => candidate.endsWith("route.ts"))
        .map((candidate) => candidate.replaceAll("\\", "/"))
        .sort()
      const content = await source(file)

      expect(routeFiles).toEqual([
        "src/app/api/snapshot-workflow/dashboard/route.ts",
        "src/app/api/snapshot-workflow/portfolio/route.ts",
      ])
      expect(Object.keys(module)).toEqual(["POST"])
      expect(content.match(/\bgetServerSession\s*\(/g)).toHaveLength(1)
      expect(content).toContain('const NO_STORE_HEADERS = { "Cache-Control": "no-store" }')
      expect(content).not.toMatch(/export\s+(?:async\s+)?function\s+GET/)
      expect(content).not.toMatch(/\b(?:NextRequest|request\.json|accountId|snapshotId)\b/)
      expect(content).not.toMatch(/\b(?:timestamp|currency|calculationVersion)\b/)
    })

    it.each([
      ["missing session", null],
      ["missing session.user", { expires: "2037-01-01" }],
      [
        "blank session.user.id",
        { user: { id: "   ", email: "audit@example.test" }, expires: "2037-01-01" },
      ],
    ])("rejects %s with 401 before the workflow", async (_label, session) => {
      getSession.mockResolvedValue(session as never)

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

    it.each([
      [
        "with email",
        { id: "audit-user", email: "audit@example.test" },
        { userId: "audit-user", email: "audit@example.test" },
      ],
      ["without email", { id: "audit-user", email: null }, { userId: "audit-user" }],
    ])("uses the verified session identity %s", async (_label, user, expectedIdentity) => {
      getSession.mockResolvedValue({ user, expires: "2037-01-01" } as never)
      workflow.mockResolvedValue(EMPTY_RESULT as never)

      const response = await post()

      expect(getSession).toHaveBeenCalledTimes(1)
      expect(workflow).toHaveBeenCalledTimes(1)
      expect(workflow).toHaveBeenCalledWith(expectedIdentity)
      expect(response.status).toBe(200)
    })

    it("ignores browser credentials, body identity, and selectors", async () => {
      getSession.mockResolvedValue({
        user: { id: "session-user", email: "session@example.test" },
        expires: "2037-01-01",
      })
      workflow.mockResolvedValue(EMPTY_RESULT as never)
      const request = new Request(`http://localhost/api/snapshot-workflow/${file}`, {
        method: "POST",
        headers: {
          Authorization: "Bearer browser-token",
          Cookie: "next-auth=session-cookie",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          sub: "caller-user",
          accountId: "caller-account",
          snapshotId: "caller-snapshot",
          timestamp: "caller-time",
          currency: "USD",
          calculationVersion: 999,
        }),
      })

      await (post as unknown as (request: Request) => Promise<Response>)(request)

      expect(workflow).toHaveBeenCalledTimes(1)
      expect(workflow).toHaveBeenCalledWith({
        userId: "session-user",
        email: "session@example.test",
      })
    })
  }
)

describe("browser and workflow inventory", () => {
  it("keeps FastAPI URLs, tokens, secrets, and server modules out of client boundaries", async () => {
    const productionFiles = (await filesBelow("src")).filter(
      (file) =>
        (file.endsWith(".ts") || file.endsWith(".tsx")) &&
        !file.includes(".test.") &&
        !file.includes(`${path.sep}generated${path.sep}`)
    )
    const clientFiles: string[] = []
    for (const file of productionFiles) {
      const content = await source(file)
      if (
        /^\s*["']use client["']/.test(content) ||
        /(?:snapshot-page-client|snapshot-dashboard-client|operational-dashboard-client)\.ts$/.test(
          file
        )
      ) {
        clientFiles.push(file)
      }
    }

    expect(clientFiles.length).toBeGreaterThan(0)
    for (const file of clientFiles) {
      const content = await source(file)
      expect(content, file).not.toMatch(
        /\/api\/v1\/(?:snapshot-refresh\/recalculate|portfolio\/snapshot|dashboard\/snapshot)/
      )
      expect(content, file).not.toMatch(
        /PYTHON_BACKEND_URL|INTERNAL_AUTH_SECRET|http:\/\/api:8010|http:\/\/localhost:8010/
      )
      expect(content, file).not.toMatch(
        /from\s+["'](?:jose|[^"']*internal-token|[^"']*server\/config)["']/
      )
    }
  })

  it("documents backend and schema PR coverage but no frontend-only workflow", async () => {
    const backend = await source(".github/workflows/backend-python.yml")
    const database = await source(".github/workflows/database-schema.yml")
    const combined = `${backend}\n${database}`

    expect(backend).toContain('      - "backend/python/**"')
    expect(database).toContain('      - "backend/python/tests/**"')
    expect(database).toContain('      - "prisma/**"')
    expect(combined).not.toMatch(/-\s+"src\/\*\*"/)
    expect(combined).not.toMatch(/-\s+"src\/app\/\*\*"/)
  })
})
