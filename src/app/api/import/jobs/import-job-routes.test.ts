import { getServerSession } from "next-auth"
import { NextRequest } from "next/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { createPythonImportApi } from "@/modules/imports/python/import-api"
import { GET } from "./[jobId]/route"
import { POST } from "./[jobId]/retry/route"

vi.mock("next-auth", () => ({ getServerSession: vi.fn() }))
vi.mock("@/lib/auth", () => ({ authOptions: {} }))
vi.mock("@/modules/imports/python/import-api", () => ({ createPythonImportApi: vi.fn() }))

const session = vi.mocked(getServerSession)
const api = vi.mocked(createPythonImportApi)

const job = {
  id: "job-a",
  account_id: "account-a",
  kind: "import_workflow" as const,
  status: "failed" as const,
  progress: {
    schema_version: 1 as const,
    phase: "posting" as const,
    completed_units: 5,
    total_units: 7,
    completed_batches: 1,
    total_batches: 1,
  },
  result: null,
  error: { code: "import_failed", message: "Import could not be completed." },
  attempt_count: 1,
  max_attempts: 5,
  manual_retry_count: 0,
  run_after: "2026-01-01T00:00:00Z",
  started_at: "2026-01-01T00:00:00Z",
  finished_at: "2026-01-01T00:01:00Z",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:01:00Z",
}

const context = { params: Promise.resolve({ jobId: "job-a" }) }

beforeEach(() => {
  vi.clearAllMocks()
  session.mockResolvedValue({ user: { id: "user-a", email: "user@example.test" }, expires: "2030" })
  api.mockReturnValue({
    getImportJob: vi.fn(async () => job),
    retryImportJob: vi.fn(async () => ({ ...job, status: "queued", error: null })),
  } as never)
})

describe("durable import job proxy routes", () => {
  it("requires a session and validates the account/job scope before proxying", async () => {
    session.mockResolvedValueOnce(null)
    expect(
      (
        await GET(
          new NextRequest("http://next.test/api/import/jobs/job-a?accountId=account-a"),
          context
        )
      ).status
    ).toBe(401)

    const invalid = await GET(
      new NextRequest("http://next.test/api/import/jobs/job-a?accountId=%20account-a"),
      context
    )
    expect(invalid.status).toBe(422)
    expect(api).not.toHaveBeenCalled()
  })

  it("returns only the owner-scoped job and fails closed on a mismatched backend identity", async () => {
    const response = await GET(
      new NextRequest("http://next.test/api/import/jobs/job-a?accountId=account-a"),
      context
    )
    expect(response.status).toBe(200)
    expect(response.headers.get("Cache-Control")).toBe("no-store")
    expect(api.mock.results[0]?.value.getImportJob).toHaveBeenCalledWith("account-a", "job-a")

    api.mockReturnValueOnce({
      getImportJob: vi.fn(async () => ({ ...job, account_id: "account-b" })),
    } as never)
    const mismatch = await GET(
      new NextRequest("http://next.test/api/import/jobs/job-a?accountId=account-a"),
      context
    )
    expect(mismatch.status).toBe(502)
  })

  it("retries through the proxy only and rejects a malformed retry body", async () => {
    const response = await POST(
      new NextRequest("http://next.test/api/import/jobs/job-a/retry", {
        method: "POST",
        body: JSON.stringify({ accountId: "account-a" }),
        headers: { "content-type": "application/json" },
      }),
      context
    )
    expect(response.status).toBe(200)
    expect(api.mock.results[0]?.value.retryImportJob).toHaveBeenCalledWith("account-a", "job-a")

    const invalid = await POST(
      new NextRequest("http://next.test/api/import/jobs/job-a/retry", {
        method: "POST",
        body: JSON.stringify({ accountId: " account-a" }),
        headers: { "content-type": "application/json" },
      }),
      context
    )
    expect(invalid.status).toBe(422)
  })
})
