import "server-only"

import { createHash } from "node:crypto"

import { describe, expect, it, vi } from "vitest"

import type { PythonApiConfig } from "@/modules/python-api/server/config"
import { runImportCanonicalWorkflow } from "./import-api"
import type { PythonImportSource } from "./import-contract"

const CONFIG: PythonApiConfig = {
  backendUrl: "https://python.example.test/base",
  internalAuthSecret: "test-internal-auth-secret-with-32-characters",
  internalAuthIssuer: "finance-app-next",
  internalAuthAudience: "finance-app-python",
  internalAuthTokenTtlSeconds: 60,
  timeoutMs: 30000,
}

const IDENTITY = { userId: "user-r4", email: "user-r4@example.test" }
const BYTES = new Uint8Array([0xef, 0xbb, 0xbf, 0x61, 0x0d, 0x0a])
const CHECKSUM = createHash("sha256").update(BYTES).digest("hex")

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function responses(source: PythonImportSource, extra: Record<string, unknown> = {}) {
  const batch = {
    id: "batch-r4",
    account_id: "account-r4",
    source,
    filename: "fixture.csv",
    file_size: BYTES.byteLength,
    file_encoding: null,
    checksum: CHECKSUM,
    status: "processing",
    rows_total: null,
    rows_imported: null,
    rows_skipped: null,
    created_at: "2036-08-03T10:00:00Z",
    completed_at: null,
    ...extra,
  }
  return [
    batch,
    {
      batch_id: "batch-r4",
      stored: true,
      idempotent: false,
      size: BYTES.byteLength,
      checksum: CHECKSUM,
      ...extra,
    },
    {
      batch_id: "batch-r4",
      status: "processing",
      rows_total: 3,
      rows_pending: 3,
      rows_failed: 0,
      ...extra,
    },
    {
      batch_id: "batch-r4",
      status: "processing",
      rows_total: 3,
      rows_normalized: 2,
      rows_needs_review: 1,
      rows_failed: 0,
      ...extra,
    },
    {
      batch_id: "batch-r4",
      status: "processing",
      rows_total: 3,
      rows_unique: 2,
      rows_duplicate: 0,
      rows_needs_review: 1,
      rows_failed: 0,
      ...extra,
    },
    {
      batch_id: "batch-r4",
      status: "processing",
      rows_total: 3,
      rows_classified: 2,
      rows_duplicate: 0,
      rows_needs_review: 1,
      rows_failed: 0,
      rows_skipped: 0,
      ...extra,
    },
    {
      batch_id: "batch-r4",
      status: "partially_completed",
      rows_total: 3,
      rows_imported: 2,
      rows_skipped: 1,
      replayed: false,
      completed_at: "2036-08-03T10:01:00Z",
      snapshot_refresh_status: "unavailable",
      ...extra,
    },
    {
      ...batch,
      status: "partially_completed",
      rows_total: 3,
      rows_imported: 2,
      rows_skipped: 1,
      completed_at: "2036-08-03T10:01:00Z",
    },
  ]
}

function workflow(
  source: PythonImportSource,
  fetchImplementation: typeof fetch,
  tokenIssuer = vi.fn(async () => "token-r4")
) {
  return {
    result: runImportCanonicalWorkflow(
      IDENTITY,
      {
        accountId: "account-r4",
        source,
        filename: "fixture.csv",
        bytes: BYTES,
      },
      { config: CONFIG, fetchImplementation, tokenIssuer }
    ),
    tokenIssuer,
  }
}

describe.each(["raiffeisenbank", "trading212", "anycoin"] as const)(
  "%s Python staged import workflow",
  (source) => {
    it("uses the exact eight-request sequence with one fresh token per request", async () => {
      const payloads = responses(source)
      const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse(payloads.shift()))
      const tokenIssuer = vi
        .fn()
        .mockResolvedValueOnce("token-1")
        .mockResolvedValueOnce("token-2")
        .mockResolvedValueOnce("token-3")
        .mockResolvedValueOnce("token-4")
        .mockResolvedValueOnce("token-5")
        .mockResolvedValueOnce("token-6")
        .mockResolvedValueOnce("token-7")
        .mockResolvedValueOnce("token-8")

      const execution = await workflow(source, fetchImplementation, tokenIssuer).result

      expect(execution.errorStatus).toBeUndefined()
      expect(execution.result).toMatchObject({
        filename: "fixture.csv",
        batchId: "batch-r4",
        status: "partially_completed",
        lastSuccessfulStage: "status",
        rowsTotal: 3,
        rowsImported: 2,
        rowsSkipped: 1,
        rowsFailed: 0,
        rowsNeedsReview: 1,
      })
      const requests = fetchImplementation.mock.calls.map(
        ([input, init]) => new Request(input, init)
      )
      expect(
        requests.map((request) => `${request.method} ${new URL(request.url).pathname}`)
      ).toEqual([
        "POST /base/api/v1/accounts/account-r4/imports",
        "PUT /base/api/v1/accounts/account-r4/imports/batch-r4/file",
        "POST /base/api/v1/accounts/account-r4/imports/batch-r4/parse",
        "POST /base/api/v1/accounts/account-r4/imports/batch-r4/normalize",
        "POST /base/api/v1/accounts/account-r4/imports/batch-r4/deduplicate",
        "POST /base/api/v1/accounts/account-r4/imports/batch-r4/classify",
        "POST /base/api/v1/accounts/account-r4/imports/batch-r4/canonical-post",
        "GET /base/api/v1/accounts/account-r4/imports/batch-r4",
      ])
      expect(tokenIssuer).toHaveBeenCalledTimes(8)
      expect(requests.map((request) => request.headers.get("Authorization"))).toEqual([
        "Bearer token-1",
        "Bearer token-2",
        "Bearer token-3",
        "Bearer token-4",
        "Bearer token-5",
        "Bearer token-6",
        "Bearer token-7",
        "Bearer token-8",
      ])
      expect(requests.every((request) => !request.headers.has("Cookie"))).toBe(true)
    })
  }
)

describe("import transport evidence", () => {
  it("hashes and uploads the exact bytes without BOM/newline conversion", async () => {
    const payloads = responses("raiffeisenbank")
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse(payloads.shift()))

    await workflow("raiffeisenbank", fetchImplementation).result

    const createRequest = new Request(...fetchImplementation.mock.calls[0])
    expect(await createRequest.json()).toEqual({
      source: "raiffeisenbank",
      filename: "fixture.csv",
      file_size: BYTES.byteLength,
      file_encoding: null,
      checksum: CHECKSUM,
    })
    const uploadRequest = new Request(...fetchImplementation.mock.calls[1])
    expect(uploadRequest.headers.get("Content-Type")).toBe("application/octet-stream")
    expect(new Uint8Array(await uploadRequest.arrayBuffer())).toEqual(BYTES)
  })

  it("projects unknown success fields out of the browser result", async () => {
    const payloads = responses("anycoin", {
      token: "must-not-leak",
      raw_import_row: "must-not-leak",
      request_id: "must-not-leak",
    })
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse(payloads.shift()))

    const execution = await workflow("anycoin", fetchImplementation).result

    expect(JSON.stringify(execution.result)).not.toMatch(
      /must-not-leak|token|raw_import_row|request_id/
    )
  })

  it("stops after the first failed stage and reports the persisted batch boundary", async () => {
    const payloads = responses("trading212")
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(payloads[0]))
      .mockResolvedValueOnce(jsonResponse(payloads[1]))
      .mockResolvedValueOnce(jsonResponse(payloads[2]))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            error: {
              code: "import_normalization_failed",
              message: "Import normalization failed.",
              request_id: "hidden",
            },
          },
          409
        )
      )

    const execution = await workflow("trading212", fetchImplementation).result

    expect(fetchImplementation).toHaveBeenCalledTimes(4)
    expect(execution).toMatchObject({
      errorStatus: 409,
      result: {
        filename: "fixture.csv",
        batchId: "batch-r4",
        status: "failed",
        lastSuccessfulStage: "parsed",
        error: {
          code: "import_normalization_failed",
          message: "Import normalization failed.",
        },
      },
    })
    expect(JSON.stringify(execution.result)).not.toContain("request_id")
  })

  it("distinguishes a duplicate create response from transport failure", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse(
        {
          error: {
            code: "import_batch_exists",
            message: "This file was already imported.",
            request_id: "hidden",
          },
        },
        409
      )
    )

    const execution = await workflow("raiffeisenbank", fetchImplementation).result

    expect(fetchImplementation).toHaveBeenCalledTimes(1)
    expect(execution).toEqual({
      result: {
        filename: "fixture.csv",
        status: "duplicate",
        rowsTotal: 0,
        rowsImported: 0,
        rowsSkipped: 0,
        rowsFailed: 0,
        rowsNeedsReview: 0,
        issues: { failed: 0, needsReview: 0 },
        error: {
          code: "import_batch_exists",
          message: "This file was already imported.",
        },
      },
    })
  })

  it.each([400, 404, 409, 422])(
    "forwards safe Python %s domain errors without internal fields",
    async (status) => {
      const fetchImplementation = vi.fn<typeof fetch>(async () =>
        jsonResponse(
          {
            error: {
              code: "safe_import_error",
              message: "The import request was rejected.",
              request_id: "hidden",
              raw_import_row: "hidden",
            },
          },
          status
        )
      )

      const execution = await workflow("raiffeisenbank", fetchImplementation).result

      expect(execution).toMatchObject({
        errorStatus: status,
        result: {
          status: "failed",
          error: {
            code: "safe_import_error",
            message: "The import request was rejected.",
          },
        },
      })
      expect(JSON.stringify(execution.result)).not.toMatch(/request_id|raw_import_row|hidden/)
    }
  )

  it.each([401, 403, 500])("maps Python %s to a generic bridge failure", async (status) => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse(
        {
          error: {
            code: "backend-secret",
            message: "Bearer secret traceback",
          },
        },
        status
      )
    )

    const execution = await workflow("anycoin", fetchImplementation).result

    expect(execution).toMatchObject({
      errorStatus: 502,
      result: {
        status: "failed",
        error: {
          code: "python_api_unavailable",
          message: "The Python API is unavailable.",
        },
      },
    })
    expect(JSON.stringify(execution.result)).not.toMatch(/backend-secret|Bearer|traceback/)
  })

  it("fails closed on response identity mismatch without continuing", async () => {
    const [batch] = responses("raiffeisenbank")
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ ...batch, account_id: "foreign-account" })
    )

    const execution = await workflow("raiffeisenbank", fetchImplementation).result

    expect(fetchImplementation).toHaveBeenCalledTimes(1)
    expect(execution).toMatchObject({
      errorStatus: 502,
      result: {
        status: "failed",
        error: { code: "python_api_contract_error" },
      },
    })
  })
})
