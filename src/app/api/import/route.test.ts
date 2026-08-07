import { getServerSession } from "next-auth"
import { NextRequest } from "next/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  createPythonImportApi,
  runImportCanonicalWorkflow,
} from "@/modules/imports/python/import-api"
import {
  recoverableBatchIds,
  type PythonImportFinalizeResponse,
} from "@/modules/imports/python/import-contract"
import { forwardedPythonError } from "@/modules/python-api/server/errors"
import * as anycoinRoute from "./anycoin/route"
import * as finalizeRoute from "./finalize/route"
import * as collectionRoute from "./route"
import * as raiffeisenbankRoute from "./raiffeisenbank/route"
import * as statusRoute from "./status/route"
import * as trading212Route from "./trading212/route"

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}))

vi.mock("@/lib/auth", () => ({
  authOptions: { providers: [] },
}))

vi.mock("@/modules/imports/python/import-api", () => ({
  runImportCanonicalWorkflow: vi.fn(),
  createPythonImportApi: vi.fn(),
}))

const getSession = vi.mocked(getServerSession)
const runWorkflow = vi.mocked(runImportCanonicalWorkflow)
const createApi = vi.mocked(createPythonImportApi)
const finalizeBatches = vi.fn(
  async (
    _accountId: string,
    batchIds: readonly string[]
  ): Promise<PythonImportFinalizeResponse> => ({
    batch_ids: [...batchIds].sort(),
    snapshot_refresh_status: batchIds.length === 0 ? "not_required" : "created",
  })
)

function completed(filename: string, batchId = `batch-${filename}`) {
  return {
    result: {
      filename,
      batchId,
      status: "completed" as const,
      lastSuccessfulStage: "status" as const,
      rowsTotal: 1,
      rowsImported: 1,
      rowsSkipped: 0,
      rowsFailed: 0,
      rowsNeedsReview: 0,
      issues: { failed: 0, needsReview: 0 },
    },
  }
}

function request(
  fields: Array<[string, string | File]>,
  path = "http://next.test/api/import"
): NextRequest {
  const formData = new FormData()
  for (const [name, value] of fields) formData.append(name, value)
  return new NextRequest(path, { method: "POST", body: formData })
}

function finalizationRequest(body: unknown): NextRequest {
  return new NextRequest("http://next.test/api/import/finalize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

const validFields = (): Array<[string, string | File]> => [
  ["accountId", "account-r4"],
  ["source", "raiffeisenbank"],
  ["file", new File([new Uint8Array([0xef, 0xbb, 0xbf, 0x61])], "fixture.csv")],
]

const INVALID_FORMS: Array<{ name: string; fields: Array<[string, string | File]> }> = [
  {
    name: "missing account",
    fields: [
      ["source", "raiffeisenbank"],
      ["file", new File(["x"], "x.csv")],
    ],
  },
  {
    name: "missing source",
    fields: [
      ["accountId", "account-r4"],
      ["file", new File(["x"], "x.csv")],
    ],
  },
  {
    name: "unsupported source",
    fields: [
      ["accountId", "account-r4"],
      ["source", "manual"],
      ["file", new File(["x"], "x.csv")],
    ],
  },
  {
    name: "zero files",
    fields: [
      ["accountId", "account-r4"],
      ["source", "raiffeisenbank"],
    ],
  },
  {
    name: "non CSV file",
    fields: [
      ["accountId", "account-r4"],
      ["source", "raiffeisenbank"],
      ["file", new File(["x"], "x.txt")],
    ],
  },
  {
    name: "caller identity",
    fields: [
      ["accountId", "account-r4"],
      ["source", "raiffeisenbank"],
      ["file", new File(["x"], "x.csv")],
      ["userId", "attacker"],
    ],
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  getSession.mockResolvedValue({
    user: { id: "user-r4", email: "user-r4@example.test" },
    expires: "2036-01-01",
  })
  runWorkflow.mockImplementation(async (_identity, input) => completed(input.filename))
  createApi.mockReturnValue({ finalizeImportBatches: finalizeBatches } as unknown as ReturnType<
    typeof createPythonImportApi
  >)
})

describe("POST /api/import", () => {
  it("exports POST only", () => {
    expect(Object.keys(collectionRoute)).toEqual(["POST"])
  })

  it.each([
    null,
    { user: undefined, expires: "2036-01-01" },
    { user: { id: " ", email: "user@example.test" }, expires: "2036-01-01" },
  ])("rejects a missing identity before Python", async (session) => {
    getSession.mockResolvedValue(session)

    const response = await collectionRoute.POST(request(validFields()))

    expect(getSession).toHaveBeenCalledTimes(1)
    expect(runWorkflow).not.toHaveBeenCalled()
    expect(response.status).toBe(401)
    expect(response.headers.get("Cache-Control")).toBe("no-store")
    expect(await response.json()).toEqual({
      error: {
        code: "authentication_required",
        message: "Authentication is required.",
      },
    })
  })

  it.each(INVALID_FORMS)("rejects $name multipart before Python", async ({ fields }) => {
    const response = await collectionRoute.POST(request(fields))

    expect(response.status).toBe(422)
    expect(runWorkflow).not.toHaveBeenCalled()
    expect(await response.json()).toEqual({
      error: {
        code: "validation_error",
        message: "Request validation failed.",
      },
    })
  })

  it("rejects malformed multipart before Python", async () => {
    const malformed = new NextRequest("http://next.test/api/import", {
      method: "POST",
      headers: { "Content-Type": "multipart/form-data; boundary=missing" },
      body: "not-a-valid-multipart-body",
    })

    const response = await collectionRoute.POST(malformed)

    expect(response.status).toBe(422)
    expect(runWorkflow).not.toHaveBeenCalled()
    expect(await response.json()).toEqual({
      error: {
        code: "validation_error",
        message: "Request validation failed.",
      },
    })
  })

  it("rejects an oversized CSV before reading or calling Python", async () => {
    const formData = new FormData()
    formData.append("accountId", "account-r4")
    formData.append("source", "raiffeisenbank")
    const file = new File(["x"], "oversized.csv")
    Object.defineProperty(file, "size", { value: 64 * 1024 * 1024 + 1 })
    formData.append("file", file)
    const oversizedRequest = {
      formData: vi.fn(async () => formData),
    } as unknown as NextRequest

    const response = await collectionRoute.POST(oversizedRequest)

    expect(response.status).toBe(422)
    expect(runWorkflow).not.toHaveBeenCalled()
  })

  it("preserves multi-file order, exact bytes, source and session identity", async () => {
    const first = new File([new Uint8Array([0xef, 0xbb, 0xbf, 1])], "first.csv")
    const second = new File([new Uint8Array([2, 0x0d, 0x0a])], "second.csv")

    const response = await collectionRoute.POST(
      request([
        ["accountId", "account-r4"],
        ["source", "anycoin"],
        ["file", first],
        ["file", second],
      ])
    )

    expect(response.status).toBe(200)
    expect(getSession).toHaveBeenCalledTimes(1)
    expect(runWorkflow).toHaveBeenCalledTimes(2)
    expect(runWorkflow.mock.calls.map(([, input]) => input.filename)).toEqual([
      "first.csv",
      "second.csv",
    ])
    expect(runWorkflow.mock.calls[0][0]).toEqual({
      userId: "user-r4",
      email: "user-r4@example.test",
    })
    expect(runWorkflow.mock.calls[0][1]).toMatchObject({
      accountId: "account-r4",
      source: "anycoin",
    })
    expect([...runWorkflow.mock.calls[0][1].bytes]).toEqual([0xef, 0xbb, 0xbf, 1])
    expect([...runWorkflow.mock.calls[1][1].bytes]).toEqual([2, 0x0d, 0x0a])
    expect(finalizeBatches).toHaveBeenCalledTimes(1)
    expect(finalizeBatches).toHaveBeenCalledWith("account-r4", [
      "batch-first.csv",
      "batch-second.csv",
    ])
    expect((await response.clone().json()).snapshotRefreshStatus).toBe("created")
    expect(JSON.stringify(await response.json())).not.toMatch(
      /user-r4@example|Authorization|Cookie|token/
    )
  })

  it("retains completed files and the failed batch boundary on partial failure", async () => {
    runWorkflow.mockResolvedValueOnce(completed("first.csv")).mockResolvedValueOnce({
      errorStatus: 409,
      result: {
        filename: "second.csv",
        batchId: "batch-second",
        status: "failed",
        lastSuccessfulStage: "parsed",
        rowsTotal: 3,
        rowsImported: 0,
        rowsSkipped: 0,
        rowsFailed: 1,
        rowsNeedsReview: 0,
        issues: { failed: 1, needsReview: 0 },
        error: {
          code: "import_normalization_failed",
          message: "Import normalization failed.",
        },
      },
    })

    const response = await collectionRoute.POST(
      request([
        ["accountId", "account-r4"],
        ["source", "trading212"],
        ["file", new File(["one"], "first.csv")],
        ["file", new File(["two"], "second.csv")],
        ["file", new File(["three"], "third.csv")],
      ])
    )
    const body = await response.json()

    expect(response.status).toBe(409)
    expect(body.partial.files.map((file: { filename: string }) => file.filename)).toEqual([
      "first.csv",
      "second.csv",
      "third.csv",
    ])
    expect(body.partial.files[1]).toMatchObject({
      batchId: "batch-second",
      lastSuccessfulStage: "parsed",
    })
    expect(body.partial.snapshotRefreshStatus).toBe("not_run")
    expect(runWorkflow).toHaveBeenCalledTimes(3)
    expect(finalizeBatches).not.toHaveBeenCalled()
  })

  it("continues past duplicate files and finalizes only persisted canonical batches", async () => {
    runWorkflow
      .mockResolvedValueOnce({
        result: {
          filename: "duplicate.csv",
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
      .mockResolvedValueOnce(completed("new.csv", "batch-new"))

    const response = await collectionRoute.POST(
      request([
        ["accountId", "account-r4"],
        ["source", "trading212"],
        ["file", new File(["same"], "duplicate.csv")],
        ["file", new File(["new"], "new.csv")],
      ])
    )
    const body = await response.json()

    expect(response.status).toBe(200)
    expect(body).toMatchObject({
      duplicateFiles: 1,
      completedFiles: 1,
      snapshotRefreshStatus: "created",
    })
    expect(finalizeBatches).toHaveBeenCalledOnce()
    expect(finalizeBatches).toHaveBeenCalledWith("account-r4", ["batch-new"])
  })

  it("asks Python to classify an all-duplicate request as not required", async () => {
    runWorkflow.mockResolvedValue({
      result: {
        filename: "duplicate.csv",
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

    const response = await collectionRoute.POST(
      request([
        ["accountId", "account-r4"],
        ["source", "trading212"],
        ["file", new File(["same"], "duplicate.csv")],
      ])
    )
    const body = await response.json()

    expect(response.status).toBe(200)
    expect(body.snapshotRefreshStatus).toBe("not_required")
    expect(recoverableBatchIds(body)).toEqual([])
    expect(finalizeBatches).toHaveBeenCalledWith("account-r4", [])
  })

  it("reports committed canonical files when request-level finalization fails", async () => {
    finalizeBatches.mockRejectedValueOnce(new Error("provider transport detail"))

    const response = await collectionRoute.POST(request(validFields()))
    const body = await response.json()

    expect(response.status).toBe(502)
    expect(body.error).toEqual({
      code: "python_api_unavailable",
      message: "The Python API is unavailable.",
    })
    expect(body.partial).toMatchObject({
      completedFiles: 1,
      snapshotRefreshStatus: "not_run",
    })
    expect(JSON.stringify(body)).not.toContain("provider transport detail")
  })

  it("recovers a canonical subset after a later file fails without re-uploading", async () => {
    runWorkflow.mockResolvedValueOnce(completed("first.csv", "batch-first")).mockResolvedValueOnce({
      errorStatus: 409,
      result: {
        filename: "second.csv",
        batchId: "batch-second",
        status: "failed",
        lastSuccessfulStage: "parsed",
        rowsTotal: 1,
        rowsImported: 0,
        rowsSkipped: 0,
        rowsFailed: 1,
        rowsNeedsReview: 0,
        issues: { failed: 1, needsReview: 0 },
        error: { code: "import_parse_failed", message: "Import parsing failed." },
      },
    })

    const initial = await collectionRoute.POST(
      request([
        ["accountId", "account-r4"],
        ["source", "trading212"],
        ["file", new File(["one"], "first.csv")],
        ["file", new File(["bad"], "second.csv")],
      ])
    )
    const partial = (await initial.json()).partial
    const batchIds = recoverableBatchIds(partial)
    const recovered = await finalizeRoute.POST(
      finalizationRequest({ accountId: "account-r4", batchIds })
    )

    expect(initial.status).toBe(409)
    expect(batchIds).toEqual(["batch-first"])
    expect(recovered.status).toBe(200)
    expect(await recovered.json()).toEqual({
      batchIds: ["batch-first"],
      snapshotRefreshStatus: "created",
    })
    expect(runWorkflow).toHaveBeenCalledTimes(2)
    expect(finalizeBatches).toHaveBeenCalledOnce()
    expect(finalizeBatches).toHaveBeenCalledWith("account-r4", ["batch-first"])
  })

  it("recovers every terminal canonical batch after a follow-up status failure", async () => {
    runWorkflow.mockResolvedValueOnce(completed("first.csv", "batch-first")).mockResolvedValueOnce({
      errorStatus: 502,
      result: {
        filename: "second.csv",
        batchId: "batch-second",
        status: "failed",
        lastSuccessfulStage: "posted",
        rowsTotal: 1,
        rowsImported: 1,
        rowsSkipped: 0,
        rowsFailed: 0,
        rowsNeedsReview: 0,
        issues: { failed: 0, needsReview: 0 },
        error: { code: "python_api_unavailable", message: "The Python API is unavailable." },
      },
    })

    const initial = await collectionRoute.POST(
      request([
        ["accountId", "account-r4"],
        ["source", "trading212"],
        ["file", new File(["one"], "first.csv")],
        ["file", new File(["two"], "second.csv")],
      ])
    )
    const partial = (await initial.json()).partial
    const batchIds = recoverableBatchIds(partial)
    await finalizeRoute.POST(finalizationRequest({ accountId: "account-r4", batchIds }))

    expect(batchIds).toEqual(["batch-first", "batch-second"])
    expect(finalizeBatches).toHaveBeenCalledWith("account-r4", ["batch-first", "batch-second"])
  })

  it("retries the same persisted IDs after finalization transport failure", async () => {
    finalizeBatches.mockRejectedValueOnce(new Error("transport detail")).mockResolvedValueOnce({
      batch_ids: ["batch-fixture.csv"],
      snapshot_refresh_status: "created",
    })

    const initial = await collectionRoute.POST(request(validFields()))
    const partial = (await initial.json()).partial
    const batchIds = recoverableBatchIds(partial)
    const recovered = await finalizeRoute.POST(
      finalizationRequest({ accountId: "account-r4", batchIds })
    )

    expect(batchIds).toEqual(["batch-fixture.csv"])
    expect(recovered.status).toBe(200)
    expect(runWorkflow).toHaveBeenCalledOnce()
    expect(finalizeBatches.mock.calls).toEqual([
      ["account-r4", ["batch-fixture.csv"]],
      ["account-r4", ["batch-fixture.csv"]],
    ])
  })

  it("retries market-unavailable finalization without re-running canonical staging", async () => {
    finalizeBatches
      .mockResolvedValueOnce({
        batch_ids: ["batch-fixture.csv"],
        snapshot_refresh_status: "unavailable",
      })
      .mockResolvedValueOnce({
        batch_ids: ["batch-fixture.csv"],
        snapshot_refresh_status: "created",
      })

    const initial = await collectionRoute.POST(request(validFields()))
    const summary = await initial.json()
    const batchIds = recoverableBatchIds(summary)
    const recovered = await finalizeRoute.POST(
      finalizationRequest({ accountId: "account-r4", batchIds })
    )

    expect(summary.snapshotRefreshStatus).toBe("unavailable")
    expect((await recovered.json()).snapshotRefreshStatus).toBe("created")
    expect(runWorkflow).toHaveBeenCalledOnce()
    expect(finalizeBatches).toHaveBeenCalledTimes(2)
  })
})

describe("POST /api/import/finalize", () => {
  it("exports POST only and issues one authenticated Python finalization", async () => {
    expect(Object.keys(finalizeRoute)).toEqual(["POST"])

    const response = await finalizeRoute.POST(
      finalizationRequest({
        accountId: "account-r4",
        batchIds: ["batch-b", "batch-a"],
      })
    )

    expect(response.status).toBe(200)
    expect(getSession).toHaveBeenCalledOnce()
    expect(createApi).toHaveBeenCalledWith({
      userId: "user-r4",
      email: "user-r4@example.test",
    })
    expect(finalizeBatches).toHaveBeenCalledOnce()
    expect(finalizeBatches).toHaveBeenCalledWith("account-r4", ["batch-b", "batch-a"])
    expect(await response.json()).toEqual({
      batchIds: ["batch-a", "batch-b"],
      snapshotRefreshStatus: "created",
    })
  })

  it.each([
    {},
    { accountId: "account-r4", batchIds: [] },
    { accountId: " account-r4", batchIds: ["batch-a"] },
    { accountId: "account-r4", batchIds: ["batch-a", "batch-a"] },
    { accountId: "account-r4", batchIds: ["batch-a"], userId: "attacker" },
    { accountId: "account-r4", batchIds: ["batch-a"], source: "trading212" },
  ])("rejects an invalid or overpowered recovery request before Python", async (body) => {
    const response = await finalizeRoute.POST(finalizationRequest(body))

    expect(response.status).toBe(422)
    expect(finalizeBatches).not.toHaveBeenCalled()
  })

  it("returns generic Python nondisclosure for a foreign batch set", async () => {
    finalizeBatches.mockRejectedValueOnce(
      forwardedPythonError(404, "import_batch_not_found", "Import batch was not found.")
    )

    const response = await finalizeRoute.POST(
      finalizationRequest({ accountId: "account-r4", batchIds: ["foreign-batch"] })
    )
    const body = await response.json()

    expect(response.status).toBe(404)
    expect(body).toEqual({
      error: {
        code: "import_batch_not_found",
        message: "Import batch was not found.",
      },
    })
    expect(JSON.stringify(body)).not.toMatch(/foreign-user|owner|token/)
  })
})

describe("provider compatibility wrappers", () => {
  it.each([
    ["raiffeisenbank", raiffeisenbankRoute.POST],
    ["trading212", trading212Route.POST],
    ["anycoin", anycoinRoute.POST],
  ] as const)("%s supplies only its fixed source to the shared workflow", async (source, post) => {
    const response = await post(
      request(
        [
          ["accountId", "account-r4"],
          ["file", new File(["x"], `${source}.csv`)],
        ],
        `http://next.test/api/import/${source}`
      )
    )

    expect(response.status).toBe(200)
    expect(runWorkflow).toHaveBeenCalledTimes(1)
    expect(runWorkflow.mock.calls[0][1].source).toBe(source)
    expect(finalizeBatches).toHaveBeenCalledTimes(1)
  })
})

describe("GET /api/import/status", () => {
  it("reads every batch in the caller supplied account scope through Python", async () => {
    const getImportBatch = vi.fn(async (_accountId: string, batchId: string) => ({
      id: batchId,
      account_id: "account-r4",
      source: "trading212" as const,
      filename: `${batchId}.csv`,
      file_size: 1,
      file_encoding: null,
      checksum: "a".repeat(64),
      status: "completed" as const,
      rows_total: 1,
      rows_imported: 1,
      rows_skipped: 0,
      created_at: "2036-01-01T00:00:00Z",
      completed_at: "2036-01-01T00:01:00Z",
    }))
    createApi.mockReturnValue({ getImportBatch } as unknown as ReturnType<
      typeof createPythonImportApi
    >)

    const response = await statusRoute.GET(
      new NextRequest("http://next.test/api/import/status?accountId=account-r4&ids=batch-1,batch-2")
    )

    expect(response.status).toBe(200)
    expect(getSession).toHaveBeenCalledTimes(1)
    expect(getImportBatch.mock.calls).toEqual([
      ["account-r4", "batch-1"],
      ["account-r4", "batch-2"],
    ])
    expect(await response.json()).toEqual({
      batches: [
        {
          id: "batch-1",
          accountId: "account-r4",
          source: "trading212",
          filename: "batch-1.csv",
          status: "completed",
          rowsTotal: 1,
          rowsImported: 1,
          rowsSkipped: 0,
        },
        {
          id: "batch-2",
          accountId: "account-r4",
          source: "trading212",
          filename: "batch-2.csv",
          status: "completed",
          rowsTotal: 1,
          rowsImported: 1,
          rowsSkipped: 0,
        },
      ],
    })
  })
})
