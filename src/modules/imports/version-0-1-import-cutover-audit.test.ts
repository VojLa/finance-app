import { createHash } from "node:crypto"

import { decodeJwt } from "jose"
import { getServerSession } from "next-auth"
import { NextRequest } from "next/server"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import * as importRoute from "@/app/api/import/route"
import { requestImport } from "@/modules/imports/python/import-client"

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}))

vi.mock("@/lib/auth", () => ({
  authOptions: { providers: [] },
}))

const getSession = vi.mocked(getServerSession)
const SECRET = "r4-internal-auth-secret-with-at-least-32-characters"

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
    user: { id: "user-r4", email: "user-r4@example.test" },
    expires: "2036-01-01",
  })
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe("version 0.1 R4 browser import acceptance", () => {
  it("connects one browser request through Next session and the real staged client", async () => {
    const bytes = new Uint8Array([0xef, 0xbb, 0xbf, 0x61, 0x0d, 0x0a])
    const checksum = createHash("sha256").update(bytes).digest("hex")
    const pythonRequests: Request[] = []
    const pythonResponses = [
      {
        id: "batch-r4",
        account_id: "account-r4",
        source: "raiffeisenbank",
        filename: "fixture.csv",
        file_size: bytes.byteLength,
        file_encoding: null,
        checksum,
        status: "processing",
        rows_total: null,
        rows_imported: null,
        rows_skipped: null,
        created_at: "2036-08-03T10:00:00Z",
        completed_at: null,
        internal_metadata: "must-not-leak",
      },
      {
        batch_id: "batch-r4",
        stored: true,
        idempotent: false,
        size: bytes.byteLength,
        checksum,
      },
      {
        batch_id: "batch-r4",
        status: "processing",
        rows_total: 1,
        rows_pending: 1,
        rows_failed: 0,
      },
      {
        batch_id: "batch-r4",
        status: "processing",
        rows_total: 1,
        rows_normalized: 1,
        rows_needs_review: 0,
        rows_failed: 0,
      },
      {
        batch_id: "batch-r4",
        status: "processing",
        rows_total: 1,
        rows_unique: 1,
        rows_duplicate: 0,
        rows_needs_review: 0,
        rows_failed: 0,
      },
      {
        batch_id: "batch-r4",
        status: "processing",
        rows_total: 1,
        rows_classified: 1,
        rows_duplicate: 0,
        rows_needs_review: 0,
        rows_failed: 0,
        rows_skipped: 0,
      },
      {
        batch_id: "batch-r4",
        status: "completed",
        rows_total: 1,
        rows_imported: 1,
        rows_skipped: 0,
        replayed: false,
        completed_at: "2036-08-03T10:01:00Z",
      },
      {
        id: "batch-r4",
        account_id: "account-r4",
        source: "raiffeisenbank",
        filename: "fixture.csv",
        file_size: bytes.byteLength,
        file_encoding: null,
        checksum,
        status: "completed",
        rows_total: 1,
        rows_imported: 1,
        rows_skipped: 0,
        created_at: "2036-08-03T10:00:00Z",
        completed_at: "2036-08-03T10:01:00Z",
        token: "must-not-leak",
      },
      {
        batch_ids: ["batch-r4"],
        snapshot_refresh_status: "created",
      },
    ]
    const serverFetch = vi.fn<typeof fetch>(async (input, init) => {
      pythonRequests.push(new Request(input, init))
      return jsonResponse(pythonResponses.shift())
    })
    vi.stubGlobal("fetch", serverFetch)

    const browserPaths: string[] = []
    const browserFetch = vi.fn<typeof fetch>(async (input, init) => {
      const url =
        typeof input === "string"
          ? new URL(input, "http://next.test")
          : input instanceof URL
            ? input
            : new URL(input.url)
      const request = new NextRequest(new Request(url, init))
      browserPaths.push(request.nextUrl.pathname)
      return importRoute.POST(request)
    })

    const result = await requestImport(
      "account-r4",
      "raiffeisenbank",
      [new File([bytes], "fixture.csv", { type: "text/csv" })],
      browserFetch
    )

    expect(browserFetch).toHaveBeenCalledTimes(1)
    expect(browserPaths).toEqual(["/api/import"])
    expect(getSession).toHaveBeenCalledTimes(1)
    expect(pythonRequests).toHaveLength(9)
    expect(
      pythonRequests.map((request) => `${request.method} ${new URL(request.url).pathname}`)
    ).toEqual([
      "POST /api/v1/accounts/account-r4/imports",
      "PUT /api/v1/accounts/account-r4/imports/batch-r4/file",
      "POST /api/v1/accounts/account-r4/imports/batch-r4/parse",
      "POST /api/v1/accounts/account-r4/imports/batch-r4/normalize",
      "POST /api/v1/accounts/account-r4/imports/batch-r4/deduplicate",
      "POST /api/v1/accounts/account-r4/imports/batch-r4/classify",
      "POST /api/v1/accounts/account-r4/imports/batch-r4/canonical-post",
      "GET /api/v1/accounts/account-r4/imports/batch-r4",
      "POST /api/v1/accounts/account-r4/imports/finalize",
    ])
    const tokens = pythonRequests.map((request) =>
      request.headers.get("Authorization")?.replace("Bearer ", "")
    )
    expect(new Set(tokens).size).toBe(9)
    expect(
      tokens.map((token) => {
        const claims = decodeJwt(token ?? "")
        return { sub: claims.sub, jti: claims.jti }
      })
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          sub: "user-r4",
          jti: expect.any(String),
        }),
      ])
    )
    expect(pythonRequests.every((request) => !request.headers.has("Cookie"))).toBe(true)
    expect(new Uint8Array(await pythonRequests[1].arrayBuffer())).toEqual(bytes)
    expect(result).toMatchObject({
      completedFiles: 1,
      snapshotRefreshStatus: "created",
      files: [
        {
          filename: "fixture.csv",
          batchId: "batch-r4",
          status: "completed",
          rowsImported: 1,
        },
      ],
    })
    expect(JSON.stringify(result)).not.toMatch(
      /token|internal_metadata|user-r4@example|Authorization|Cookie/
    )
  })
})
