import { describe, expect, it, vi } from "vitest"

import { requestImport, requestImportJob, retryImportJob } from "./import-client"
import type { ImportClientError } from "./import-client"

const job = {
  id: "job-a",
  account_id: "account-a",
  kind: "import_workflow",
  status: "queued",
  attempt_count: 0,
  max_attempts: 5,
  manual_retry_count: 0,
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
  run_after: "2026-01-01T00:00:00",
  started_at: null,
  finished_at: null,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
}

describe("durable import browser client", () => {
  it("starts one multipart upload without client timeout/cancellation", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>(async (path, init) => {
      expect(path).toBe("/api/import")
      expect(init?.method).toBe("POST")
      expect(init?.signal).toBeUndefined()
      return new Response(
        JSON.stringify({ job, acceptedBatchIds: ["batch-x"], rejectedFiles: [] }),
        { status: 202, headers: { "content-type": "application/json" } }
      )
    })
    await expect(
      requestImport("account-a", "trading212", [new File(["csv"], "x.csv")], fetch)
    ).resolves.toMatchObject({ job })
  })

  it("polls and retries only through thin job routes", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify(job), { headers: { "content-type": "application/json" } })
    )
    await requestImportJob("account-a", "job-a", fetch)
    await retryImportJob("account-a", "job-a", fetch)
    expect(fetch.mock.calls.map(([path]) => String(path))).toEqual([
      "/api/import/jobs/job-a?accountId=account-a",
      "/api/import/jobs/job-a/retry",
    ])
  })

  it("keeps safe errors and rejects a malformed or foreign job response", async () => {
    const safeFailure = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(
          JSON.stringify({
            error: { code: "job_not_found", message: "Import job was not found." },
          }),
          { status: 404, headers: { "content-type": "application/json" } }
        )
    )
    await expect(requestImportJob("account-a", "job-a", safeFailure)).rejects.toMatchObject({
      status: 404,
      code: "job_not_found",
    } satisfies Partial<ImportClientError>)

    const malformed = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify({ ...job, unexpected: "secret" }), {
          headers: { "content-type": "application/json" },
        })
    )
    await expect(requestImportJob("account-a", "job-a", malformed)).rejects.toMatchObject({
      status: 502,
      code: "python_api_contract_error",
    } satisfies Partial<ImportClientError>)

    const foreign = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify({ ...job, account_id: "account-b" }), {
          headers: { "content-type": "application/json" },
        })
    )
    await expect(requestImportJob("account-a", "job-a", foreign)).rejects.toMatchObject({
      status: 502,
      code: "python_api_contract_error",
    } satisfies Partial<ImportClientError>)
  })

  it("requires the exact durable acceptance shape", async () => {
    const invalidAcceptance = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(
          JSON.stringify({ job, acceptedBatchIds: ["batch-b", "batch-a"], rejectedFiles: [] }),
          {
            status: 202,
            headers: { "content-type": "application/json" },
          }
        )
    )
    await expect(
      requestImport("account-a", "trading212", [new File(["csv"], "x.csv")], invalidAcceptance)
    ).rejects.toMatchObject({
      status: 502,
      code: "python_api_contract_error",
    } satisfies Partial<ImportClientError>)
  })
})
