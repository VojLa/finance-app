import { getServerSession } from "next-auth"
import { NextRequest } from "next/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { createPythonImportApi } from "@/modules/imports/python/import-api"
import * as route from "./route"

vi.mock("next-auth", () => ({ getServerSession: vi.fn() }))
vi.mock("@/lib/auth", () => ({ authOptions: {} }))
vi.mock("@/modules/imports/python/import-api", () => ({ createPythonImportApi: vi.fn() }))

const session = vi.mocked(getServerSession)
const api = vi.mocked(createPythonImportApi)
let client: {
  createImportBatch: ReturnType<typeof vi.fn>
  uploadImportFile: ReturnType<typeof vi.fn>
  startImportJob: ReturnType<typeof vi.fn>
}

function request(files = [new File(["csv"], "one.csv")]) {
  const body = new FormData()
  body.append("accountId", "account-a")
  body.append("source", "trading212")
  files.forEach((file) => body.append("file", file))
  return new NextRequest("http://next.test/api/import", { method: "POST", body })
}

beforeEach(() => {
  vi.clearAllMocks()
  session.mockResolvedValue({ user: { id: "user-a", email: "user@example.test" }, expires: "2030" })
  let checksum = ""
  client = {
    createImportBatch: vi.fn(async (_account, payload) => {
      checksum = payload.checksum
      return {
        id: `batch-${payload.filename}`,
        account_id: "account-a",
        source: payload.source,
        filename: payload.filename,
        file_size: payload.file_size,
        file_encoding: null,
        checksum,
        status: "pending",
      }
    }),
    uploadImportFile: vi.fn(async (_account, batchId, bytes) => ({
      batch_id: batchId,
      size: bytes.byteLength,
      checksum,
    })),
    startImportJob: vi.fn(async () => ({
      id: "job-a",
      account_id: "account-a",
      status: "queued",
      kind: "import_workflow",
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
    })),
  }
  api.mockReturnValue(client as never)
})

describe("POST /api/import durable job handoff", () => {
  it("returns 202 after registration/upload and exactly one durable job start", async () => {
    const response = await route.POST(request())
    if (response.status !== 202) throw new Error(await response.text())
    expect(api).toHaveBeenCalledWith({ userId: "user-a", email: "user@example.test" })
    expect(client.startImportJob).toHaveBeenCalledWith("account-a", ["batch-one.csv"])
    expect(await response.json()).toMatchObject({
      job: { id: "job-a", status: "queued" },
      rejectedFiles: [],
    })
  })

  it("rejects malformed input before any Python call", async () => {
    const body = new FormData()
    body.append("accountId", "account-a")
    const response = await route.POST(
      new NextRequest("http://next.test/api/import", { method: "POST", body })
    )
    expect(response.status).toBe(422)
    expect(api).not.toHaveBeenCalled()
  })

  it("continues after an individual safe failure and enqueues every accepted batch once", async () => {
    const checksums = new Map<string, string>()
    client.createImportBatch.mockImplementation(async (_account, payload) => {
      if (payload.filename === "bad.csv") {
        const error = new Error("Bad file") as Error & { status: number; code: string }
        error.status = 422
        error.code = "import_file_rejected"
        throw error
      }
      const batchId = payload.filename === "z.csv" ? "batch-z" : "batch-a"
      checksums.set(batchId, payload.checksum)
      return {
        id: batchId,
        account_id: "account-a",
        source: payload.source,
        filename: payload.filename,
        file_size: payload.file_size,
        file_encoding: null,
        checksum: payload.checksum,
        status: "pending",
      }
    })
    client.uploadImportFile.mockImplementation(async (_account, batchId, bytes) => ({
      batch_id: batchId,
      size: bytes.byteLength,
      checksum: checksums.get(batchId),
    }))
    const response = await route.POST(
      request([
        new File(["csv"], "z.csv"),
        new File(["csv"], "bad.csv"),
        new File(["csv"], "a.csv"),
      ])
    )

    if (response.status !== 202) throw new Error(await response.text())
    expect(client.startImportJob).toHaveBeenCalledTimes(1)
    expect(client.startImportJob).toHaveBeenCalledWith("account-a", ["batch-a", "batch-z"])
    expect(await response.json()).toMatchObject({
      acceptedBatchIds: ["batch-a", "batch-z"],
      rejectedFiles: [{ filename: "bad.csv", code: "python_api_unavailable" }],
    })
  })

  it("re-enqueues an exact registration replay after the worker already advanced the batch", async () => {
    client.createImportBatch.mockImplementation(async (_account, payload) => ({
      id: "batch-existing",
      account_id: "account-a",
      source: payload.source,
      filename: payload.filename,
      file_size: payload.file_size,
      file_encoding: null,
      checksum: payload.checksum,
      status: "processing",
    }))

    const response = await route.POST(request())

    expect(response.status).toBe(202)
    expect(client.uploadImportFile).not.toHaveBeenCalled()
    expect(client.startImportJob).toHaveBeenCalledWith("account-a", ["batch-existing"])
  })

  it("collapses repeated copies of the same canonical batch into one job input", async () => {
    client.createImportBatch.mockImplementation(async (_account, payload) => ({
      id: "batch-same",
      account_id: "account-a",
      source: payload.source,
      filename: payload.filename,
      file_size: payload.file_size,
      file_encoding: null,
      checksum: payload.checksum,
      status: "processing",
    }))

    const response = await route.POST(
      request([new File(["csv"], "same.csv"), new File(["csv"], "same.csv")])
    )

    expect(response.status).toBe(202)
    expect(client.startImportJob).toHaveBeenCalledWith("account-a", ["batch-same"])
    expect(await response.json()).toMatchObject({ acceptedBatchIds: ["batch-same"] })
  })

  it("does not enqueue a job when no file reached the durable upload boundary", async () => {
    client.createImportBatch.mockRejectedValue(new Error("offline"))
    const response = await route.POST(request([new File(["csv"], "a.csv")]))

    expect(response.status).toBe(502)
    expect(client.startImportJob).not.toHaveBeenCalled()
  })

  it("rejects an aggregate upload over the cap before creating any Python batch", async () => {
    const tooLarge = new File([new Uint8Array(64 * 1024 * 1024 + 1)], "large.csv")
    const response = await route.POST(request([tooLarge]))

    expect(response.status).toBe(422)
    expect(api).not.toHaveBeenCalled()
  })

  it("has no synchronous stage authority", async () => {
    const source = await import("node:fs/promises").then(({ readFile }) =>
      readFile("src/modules/imports/python/import-route.ts", "utf8")
    )
    expect(source).not.toMatch(
      /parseImportBatch|normalizeImportBatch|deduplicateImportBatch|classifyImportBatch|canonicalPostImportBatch|finalizeImportBatches/
    )
    expect(source).toContain("startImportJob")
  })
})
