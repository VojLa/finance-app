import { getServerSession } from "next-auth"
import { NextRequest } from "next/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { createPythonImportApi } from "@/modules/imports/python/import-api"
import { forwardedPythonError } from "@/modules/python-api/server/errors"
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
        status: "upload_required",
        batch: {
          id: `batch-${payload.filename}`,
          account_id: "account-a",
          source: payload.source,
          filename: payload.filename,
          file_size: payload.file_size,
          file_encoding: null,
          checksum,
          status: "pending",
        },
        job: null,
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
        status: "upload_required",
        batch: {
          id: batchId,
          account_id: "account-a",
          source: payload.source,
          filename: payload.filename,
          file_size: payload.file_size,
          file_encoding: null,
          checksum: payload.checksum,
          status: "pending",
        },
        job: null,
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

  it("returns the existing resumable job without uploading or enqueuing it again", async () => {
    client.createImportBatch.mockImplementation(async (_account, _payload) => ({
      status: "resume_job",
      batch: null,
      job: {
        id: "job-existing",
        account_id: "account-a",
        status: "running",
      },
    }))

    const response = await route.POST(request())

    expect(response.status).toBe(202)
    expect(client.uploadImportFile).not.toHaveBeenCalled()
    expect(client.startImportJob).not.toHaveBeenCalled()
    expect(await response.json()).toMatchObject({
      outcome: "resumed",
      acceptedBatchIds: [],
      job: { id: "job-existing", status: "running" },
    })
  })

  it("fails closed before uploading when registration mixes a resumable job with a new file", async () => {
    client.createImportBatch.mockImplementation(async (_account, payload) => {
      if (payload.filename === "resume.csv") {
        return {
          status: "resume_job",
          batch: null,
          job: { id: "job-existing", account_id: "account-a", status: "failed" },
        }
      }
      return {
        status: "upload_required",
        batch: {
          id: "batch-new",
          account_id: "account-a",
          source: payload.source,
          filename: payload.filename,
          file_size: payload.file_size,
          file_encoding: null,
          checksum: payload.checksum,
          status: "pending",
        },
        job: null,
      }
    })

    const response = await route.POST(
      request([new File(["resume"], "resume.csv"), new File(["new"], "new.csv")])
    )

    expect(response.status).toBe(502)
    expect(client.uploadImportFile).not.toHaveBeenCalled()
    expect(client.startImportJob).not.toHaveBeenCalled()
  })

  it("fails closed when registration returns distinct resumable jobs", async () => {
    client.createImportBatch.mockImplementation(async (_account, payload) => ({
      status: "resume_job",
      batch: null,
      job: {
        id: payload.filename === "first.csv" ? "job-first" : "job-second",
        account_id: "account-a",
        status: "running",
      },
    }))

    const response = await route.POST(
      request([new File(["first"], "first.csv"), new File(["second"], "second.csv")])
    )

    expect(response.status).toBe(502)
    expect(client.uploadImportFile).not.toHaveBeenCalled()
    expect(client.startImportJob).not.toHaveBeenCalled()
  })

  it("uploads and enqueues an exact pending registration replay", async () => {
    const response = await route.POST(request())

    expect(response.status).toBe(202)
    expect(client.uploadImportFile).toHaveBeenCalledWith(
      "account-a",
      "batch-one.csv",
      expect.any(Uint8Array)
    )
    expect(client.startImportJob).toHaveBeenCalledWith("account-a", ["batch-one.csv"])
  })

  it("hands a pending-to-processing upload race to the canonical durable job", async () => {
    client.uploadImportFile.mockRejectedValue(
      forwardedPythonError(
        409,
        "import_upload_state_invalid",
        "The import batch does not accept a raw file upload in its current state."
      )
    )
    client.startImportJob.mockResolvedValue({
      id: "job-existing",
      account_id: "account-a",
      status: "running",
    })

    const response = await route.POST(request())

    expect(response.status).toBe(202)
    expect(client.uploadImportFile).toHaveBeenCalledWith(
      "account-a",
      "batch-one.csv",
      expect.any(Uint8Array)
    )
    expect(client.startImportJob).toHaveBeenCalledWith("account-a", ["batch-one.csv"])
    expect(await response.json()).toMatchObject({
      outcome: "resumed",
      acceptedBatchIds: [],
      job: { id: "job-existing", status: "running" },
    })
  })

  it("hands a pending-to-terminal upload race to the failed canonical job", async () => {
    client.uploadImportFile.mockRejectedValue(
      forwardedPythonError(
        409,
        "import_batch_already_imported",
        "This import file has already been processed."
      )
    )
    client.startImportJob.mockResolvedValue({
      id: "job-failed",
      account_id: "account-a",
      status: "failed",
    })

    const response = await route.POST(request())

    expect(response.status).toBe(202)
    expect(client.startImportJob).toHaveBeenCalledTimes(1)
    expect(client.startImportJob).toHaveBeenCalledWith("account-a", ["batch-one.csv"])
    expect(await response.json()).toMatchObject({
      outcome: "resumed",
      acceptedBatchIds: [],
      job: { id: "job-failed", status: "failed" },
    })
  })

  it("maps a completed job found through the terminal upload race to the localized duplicate outcome", async () => {
    client.uploadImportFile.mockRejectedValue(
      forwardedPythonError(
        409,
        "import_batch_already_imported",
        "This import file has already been processed."
      )
    )
    client.startImportJob.mockResolvedValue({
      id: "job-completed",
      account_id: "account-a",
      status: "completed",
    })

    const response = await route.POST(request())

    expect(response.status).toBe(409)
    expect(await response.json()).toEqual({
      error: {
        code: "import_batch_already_imported",
        message: "Soubor už byl pro tento účet importován. Nebude importován znovu.",
      },
    })
  })

  it("keeps a terminal upload race without a canonical job as the safe backend conflict", async () => {
    client.uploadImportFile.mockRejectedValue(
      forwardedPythonError(
        409,
        "import_batch_already_imported",
        "This import file has already been processed."
      )
    )
    client.startImportJob.mockRejectedValue(
      forwardedPythonError(
        409,
        "background_job_enqueue_state_invalid",
        "The import batches are not available for background processing."
      )
    )

    const response = await route.POST(request())

    expect(response.status).toBe(409)
    expect(await response.json()).toEqual({
      error: {
        code: "background_job_enqueue_state_invalid",
        message: "The import batches are not available for background processing.",
      },
    })
    expect(client.startImportJob).toHaveBeenCalledTimes(1)
  })

  it.each([
    [
      "a different conflict code",
      forwardedPythonError(409, "import_upload_mismatch", "The uploaded file does not match."),
      409,
    ],
    [
      "the upload-state code with a different status",
      forwardedPythonError(
        422,
        "import_upload_state_invalid",
        "The import batch does not accept this upload."
      ),
      422,
    ],
  ])("does not treat %s as a processing replay", async (_description, uploadError, status) => {
    client.uploadImportFile.mockRejectedValue(uploadError)

    const response = await route.POST(request())

    expect(response.status).toBe(status)
    expect(client.startImportJob).not.toHaveBeenCalled()
  })

  it("does not upload or enqueue a completed or partially completed import", async () => {
    client.createImportBatch.mockRejectedValue(
      forwardedPythonError(
        409,
        "import_batch_already_imported",
        "The import batch was already imported."
      )
    )

    const response = await route.POST(
      request([new File(["completed"], "completed.csv"), new File(["partial"], "partial.csv")])
    )

    expect(response.status).toBe(409)
    expect(await response.json()).toEqual({
      error: {
        code: "import_batch_already_imported",
        message: "Soubor už byl pro tento účet importován. Nebude importován znovu.",
      },
    })
    expect(client.uploadImportFile).not.toHaveBeenCalled()
    expect(client.startImportJob).not.toHaveBeenCalled()
  })

  it("reports an already imported file but enqueues the remaining accepted files once", async () => {
    let newChecksum = ""
    client.createImportBatch.mockImplementation(async (_account, payload) => {
      if (payload.filename === "old.csv") {
        throw forwardedPythonError(
          409,
          "import_batch_already_imported",
          "The import batch was already imported."
        )
      }
      newChecksum = payload.checksum
      return {
        status: "upload_required",
        batch: {
          id: "batch-new",
          account_id: "account-a",
          source: payload.source,
          filename: payload.filename,
          file_size: payload.file_size,
          file_encoding: null,
          checksum: payload.checksum,
          status: "pending",
        },
        job: null,
      }
    })
    client.uploadImportFile.mockImplementation(async (_account, batchId, bytes) => ({
      batch_id: batchId,
      size: bytes.byteLength,
      checksum: newChecksum,
    }))

    const response = await route.POST(
      request([new File(["old"], "old.csv"), new File(["new"], "new.csv")])
    )

    expect(response.status).toBe(202)
    expect(await response.json()).toMatchObject({
      acceptedBatchIds: ["batch-new"],
      rejectedFiles: [
        {
          filename: "old.csv",
          code: "import_batch_already_imported",
          message: "Soubor už byl pro tento účet importován. Nebude importován znovu.",
        },
      ],
    })
    expect(client.uploadImportFile).toHaveBeenCalledTimes(1)
    expect(client.uploadImportFile).toHaveBeenCalledWith(
      "account-a",
      "batch-new",
      expect.any(Uint8Array)
    )
    expect(client.startImportJob).toHaveBeenCalledWith("account-a", ["batch-new"])
  })

  it("collapses repeated copies of the same resumable job without batch identity leakage", async () => {
    client.createImportBatch.mockImplementation(async (_account, _payload) => ({
      status: "resume_job",
      batch: null,
      job: { id: "job-same", account_id: "account-a", status: "queued" },
    }))

    const response = await route.POST(
      request([new File(["csv"], "same.csv"), new File(["csv"], "same.csv")])
    )

    expect(response.status).toBe(202)
    expect(client.startImportJob).not.toHaveBeenCalled()
    expect(await response.json()).toMatchObject({
      outcome: "resumed",
      acceptedBatchIds: [],
      job: { id: "job-same" },
    })
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
