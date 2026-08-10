import { createHash } from "node:crypto"

import { decodeJwt } from "jose"
import { getServerSession } from "next-auth"
import { NextRequest } from "next/server"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import * as importRoute from "@/app/api/import/route"
import { requestImport } from "@/modules/imports/python/import-client"

vi.mock("next-auth", () => ({ getServerSession: vi.fn() }))
vi.mock("@/lib/auth", () => ({ authOptions: { providers: [] } }))

const getSession = vi.mocked(getServerSession)
const SECRET = "r12-internal-auth-secret-with-at-least-32-characters"

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

beforeEach(() => {
  vi.stubEnv("PYTHON_BACKEND_URL", "https://python.example.test")
  vi.stubEnv("INTERNAL_AUTH_SECRET", SECRET)
  vi.stubEnv("INTERNAL_AUTH_ISSUER", "finance-app-next")
  vi.stubEnv("INTERNAL_AUTH_AUDIENCE", "finance-app-python")
  vi.stubEnv("INTERNAL_AUTH_TOKEN_TTL_SECONDS", "60")
  vi.stubEnv("PYTHON_API_TIMEOUT_MS", "30000")
  getSession.mockResolvedValue({
    user: { id: "user-r12", email: "user-r12@example.test" },
    expires: "2036-01-01",
  })
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe("version 0.1 durable browser import acceptance", () => {
  it("registers and uploads once, then hands all processing to one Python job", async () => {
    const bytes = new Uint8Array([0xef, 0xbb, 0xbf, 0x61, 0x0d, 0x0a])
    const checksum = createHash("sha256").update(bytes).digest("hex")
    const job = {
      id: "job-r12",
      account_id: "account-r12",
      kind: "import_workflow",
      status: "queued",
      progress: {
        schema_version: 1,
        phase: "queued",
        completed_units: 0,
        total_units: 7,
        completed_batches: 0,
        total_batches: 1,
      },
      result: null,
      error: null,
      attempt_count: 0,
      max_attempts: 5,
      manual_retry_count: 0,
      run_after: "2036-08-03T10:00:00",
      started_at: null,
      finished_at: null,
      created_at: "2036-08-03T10:00:00",
      updated_at: "2036-08-03T10:00:00",
    }
    const pythonResponses = [
      {
        id: "batch-r12",
        account_id: "account-r12",
        source: "raiffeisenbank",
        filename: "fixture.csv",
        file_size: bytes.byteLength,
        file_encoding: null,
        checksum,
        status: "pending",
        rows_total: null,
        rows_imported: null,
        rows_skipped: null,
        created_at: "2036-08-03T10:00:00",
        completed_at: null,
        internal_metadata: "must-not-leak",
      },
      {
        batch_id: "batch-r12",
        stored: true,
        idempotent: false,
        size: bytes.byteLength,
        checksum,
      },
      job,
    ]
    const pythonRequests: Request[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input, init) => {
        pythonRequests.push(new Request(input, init))
        return jsonResponse(pythonResponses.shift(), pythonRequests.length === 3 ? 202 : 200)
      })
    )
    const browserFetch = vi.fn<typeof fetch>(async (input, init) => {
      const url =
        typeof input === "string"
          ? new URL(input, "http://next.test")
          : input instanceof URL
            ? input
            : new URL(input.url)
      return importRoute.POST(new NextRequest(new Request(url, init)))
    })

    const result = await requestImport(
      "account-r12",
      "raiffeisenbank",
      [new File([bytes], "fixture.csv", { type: "text/csv" })],
      browserFetch
    )

    expect(browserFetch).toHaveBeenCalledTimes(1)
    expect(getSession).toHaveBeenCalledTimes(1)
    expect(
      pythonRequests.map((request) => `${request.method} ${new URL(request.url).pathname}`)
    ).toEqual([
      "POST /api/v1/accounts/account-r12/imports",
      "PUT /api/v1/accounts/account-r12/imports/batch-r12/file",
      "POST /api/v1/accounts/account-r12/imports/jobs",
    ])
    const tokens = pythonRequests.map((request) =>
      request.headers.get("Authorization")?.replace("Bearer ", "")
    )
    expect(new Set(tokens).size).toBe(3)
    expect(tokens.map((token) => decodeJwt(token ?? "").sub)).toEqual([
      "user-r12",
      "user-r12",
      "user-r12",
    ])
    expect(pythonRequests.every((request) => !request.headers.has("Cookie"))).toBe(true)
    expect(new Uint8Array(await pythonRequests[1].arrayBuffer())).toEqual(bytes)
    expect(result).toEqual({ job, acceptedBatchIds: ["batch-r12"], rejectedFiles: [] })
    expect(JSON.stringify(result)).not.toMatch(
      /internal_metadata|user-r12@example|Authorization|Cookie/
    )
  })
})
