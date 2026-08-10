import "server-only"

import { describe, expect, it, vi } from "vitest"

import type { PythonApiConfig } from "@/modules/python-api/server/config"
import { createPythonImportApi } from "./import-api"

const CONFIG: PythonApiConfig = {
  backendUrl: "https://python.example.test/base",
  internalAuthSecret: "test-internal-auth-secret-with-32-characters",
  internalAuthIssuer: "finance-app-next",
  internalAuthAudience: "finance-app-python",
  internalAuthTokenTtlSeconds: 60,
  timeoutMs: 30000,
}

const IDENTITY = { userId: "user-r12", email: "user-r12@example.test" }
const BYTES = new Uint8Array([0xef, 0xbb, 0xbf, 0x61, 0x0d, 0x0a])

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function batch() {
  return {
    id: "batch-r12",
    account_id: "account-r12",
    source: "trading212",
    filename: "fixture.csv",
    file_size: BYTES.byteLength,
    file_encoding: null,
    checksum: "checksum-r12",
    status: "pending",
    rows_total: null,
    rows_imported: null,
    rows_skipped: null,
    created_at: "2036-08-03T10:00:00Z",
    completed_at: null,
  }
}

function job(status: "queued" | "running" | "retry_wait" | "completed" | "failed" = "queued") {
  return {
    id: "job-r12",
    account_id: "account-r12",
    kind: "import_workflow",
    status,
    progress: {
      schema_version: 1,
      phase: status === "completed" ? "completed" : "queued",
      completed_units: status === "completed" ? 7 : 0,
      total_units: 7,
      completed_batches: status === "completed" ? 1 : 0,
      total_batches: 1,
    },
    result:
      status === "completed"
        ? {
            schema_version: 1,
            batch_ids: ["batch-r12"],
            rows_total: 1,
            rows_imported: 1,
            rows_skipped: 0,
            snapshot_refresh_status: "created",
            completed_at: "2036-08-03T10:01:00Z",
          }
        : null,
    error: status === "failed" ? { code: "import_failed", message: "Import failed." } : null,
    attempt_count: 0,
    max_attempts: 5,
    manual_retry_count: 0,
    run_after: "2036-08-03T10:00:00Z",
    started_at: null,
    finished_at: null,
    created_at: "2036-08-03T10:00:00Z",
    updated_at: "2036-08-03T10:00:00Z",
  }
}

describe("durable Python import transport", () => {
  it("registers/uploads then starts, reads, and retries a job with fresh server tokens", async () => {
    const responses: unknown[] = [
      { ...batch(), raw_import_row: "must-not-leak" },
      {
        batch_id: "batch-r12",
        stored: true,
        idempotent: false,
        size: BYTES.byteLength,
        checksum: "checksum-r12",
      },
      job(),
      job("running"),
      job(),
    ]
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse(responses.shift()))
    const tokenIssuer = vi
      .fn()
      .mockResolvedValueOnce("token-1")
      .mockResolvedValueOnce("token-2")
      .mockResolvedValueOnce("token-3")
      .mockResolvedValueOnce("token-4")
      .mockResolvedValueOnce("token-5")
    const api = createPythonImportApi(IDENTITY, {
      config: CONFIG,
      fetchImplementation,
      tokenIssuer,
    })

    const created = await api.createImportBatch("account-r12", {
      source: "trading212",
      filename: "fixture.csv",
      file_size: BYTES.byteLength,
      file_encoding: null,
      checksum: "checksum-r12",
    })
    await api.uploadImportFile("account-r12", created.id, BYTES)
    await api.startImportJob("account-r12", [created.id])
    await api.getImportJob("account-r12", "job-r12")
    await api.retryImportJob("account-r12", "job-r12")

    expect(created).not.toHaveProperty("raw_import_row")
    const requests = fetchImplementation.mock.calls.map(([input, init]) => new Request(input, init))
    expect(requests.map((request) => `${request.method} ${new URL(request.url).pathname}`)).toEqual(
      [
        "POST /base/api/v1/accounts/account-r12/imports",
        "PUT /base/api/v1/accounts/account-r12/imports/batch-r12/file",
        "POST /base/api/v1/accounts/account-r12/imports/jobs",
        "GET /base/api/v1/accounts/account-r12/imports/jobs/job-r12",
        "POST /base/api/v1/accounts/account-r12/imports/jobs/job-r12/retry",
      ]
    )
    expect(tokenIssuer).toHaveBeenCalledTimes(5)
    expect(requests.map((request) => request.headers.get("Authorization"))).toEqual([
      "Bearer token-1",
      "Bearer token-2",
      "Bearer token-3",
      "Bearer token-4",
      "Bearer token-5",
    ])
    expect(requests.every((request) => !request.headers.has("Cookie"))).toBe(true)
    expect(await new Request(...fetchImplementation.mock.calls[1]!).arrayBuffer()).toEqual(
      BYTES.buffer
    )
  })

  it("forwards only safe Python domain errors and fails closed on invalid job data", async () => {
    const safeFailure = vi.fn<typeof fetch>(async () =>
      jsonResponse(
        { error: { code: "import_file_rejected", message: "This file was rejected." } },
        422
      )
    )
    const safeApi = createPythonImportApi(IDENTITY, {
      config: CONFIG,
      fetchImplementation: safeFailure,
      tokenIssuer: vi.fn(async () => "token"),
    })
    await expect(safeApi.startImportJob("account-r12", ["batch-r12"])).rejects.toMatchObject({
      status: 422,
      code: "import_file_rejected",
      message: "This file was rejected.",
    })

    const invalidJob = vi.fn<typeof fetch>(async () =>
      jsonResponse({ ...job(), internal_trace: "secret" })
    )
    const invalidApi = createPythonImportApi(IDENTITY, {
      config: CONFIG,
      fetchImplementation: invalidJob,
      tokenIssuer: vi.fn(async () => "token"),
    })
    await expect(invalidApi.getImportJob("account-r12", "job-r12")).rejects.toMatchObject({
      status: 502,
      code: "python_api_contract_error",
    })
  })
})
