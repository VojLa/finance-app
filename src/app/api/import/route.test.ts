import { getServerSession } from "next-auth"
import { NextRequest } from "next/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { createPythonImportApi, runImportWorkflow } from "@/modules/imports/python/import-api"
import * as anycoinRoute from "./anycoin/route"
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
  runImportWorkflow: vi.fn(),
  createPythonImportApi: vi.fn(),
}))

const getSession = vi.mocked(getServerSession)
const runWorkflow = vi.mocked(runImportWorkflow)
const createApi = vi.mocked(createPythonImportApi)

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
      ])
    )
    const body = await response.json()

    expect(response.status).toBe(409)
    expect(body.partial.files.map((file: { filename: string }) => file.filename)).toEqual([
      "first.csv",
      "second.csv",
    ])
    expect(body.partial.files[1]).toMatchObject({
      batchId: "batch-second",
      lastSuccessfulStage: "parsed",
    })
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
