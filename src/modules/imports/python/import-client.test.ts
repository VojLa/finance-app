import { describe, expect, it, vi } from "vitest"

import { requestImport } from "./import-client"

function summary() {
  return {
    files: [
      {
        filename: "first.csv",
        batchId: "batch-1",
        status: "completed",
        lastSuccessfulStage: "status",
        rowsTotal: 2,
        rowsImported: 2,
        rowsSkipped: 0,
        rowsFailed: 0,
        rowsNeedsReview: 0,
        issues: { failed: 0, needsReview: 0 },
      },
    ],
    rowsTotal: 2,
    rowsImported: 2,
    rowsSkipped: 0,
    rowsFailed: 0,
    rowsNeedsReview: 0,
    completedFiles: 1,
    duplicateFiles: 0,
    failedFiles: 0,
  }
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("typed browser import client", () => {
  it("uses one same-origin no-store multipart request and preserves file order", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () => jsonResponse(summary()))
    const files = [
      new File([new Uint8Array([1, 2])], "first.csv", { type: "text/csv" }),
      new File([new Uint8Array([3, 4])], "second.csv", { type: "text/csv" }),
    ]

    await requestImport("account-1", "trading212", files, fetchImplementation)

    expect(fetchImplementation).toHaveBeenCalledTimes(1)
    const [path, init] = fetchImplementation.mock.calls[0]
    expect(path).toBe("/api/import")
    expect(init).toMatchObject({ method: "POST", cache: "no-store" })
    expect(init?.headers).toBeUndefined()
    const body = init?.body as FormData
    expect(body.get("accountId")).toBe("account-1")
    expect(body.get("source")).toBe("trading212")
    expect(body.getAll("file")).toEqual(files)
  })

  it("retains a safe partial summary on a per-file route failure", async () => {
    const partial = summary()
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse(
        {
          error: {
            code: "import_batch_exists",
            message: "This file was already imported.",
            request_id: "hidden",
          },
          partial,
        },
        409
      )
    )

    await expect(
      requestImport("account-1", "anycoin", [new File(["x"], "first.csv")], fetchImplementation)
    ).rejects.toMatchObject({
      status: 409,
      code: "import_batch_exists",
      message: "This file was already imported.",
      partial,
    })
  })

  it.each([
    new Response("raw traceback", { status: 500, headers: { "Content-Type": "text/plain" } }),
    jsonResponse({ token: "raw bearer" }, 502),
  ])("maps malformed errors to a safe unavailable result without retry", async (response) => {
    const fetchImplementation = vi.fn<typeof fetch>(async () => response.clone())

    await expect(
      requestImport(
        "account-1",
        "raiffeisenbank",
        [new File(["x"], "first.csv")],
        fetchImplementation
      )
    ).rejects.toMatchObject({
      status: 502,
      code: "python_api_unavailable",
      message: "Import API není dostupné.",
    })
    expect(fetchImplementation).toHaveBeenCalledTimes(1)
  })

  it("fails closed on an invalid or extra-only success response", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async () =>
      jsonResponse({ ...summary(), files: [{ token: "must-not-leak" }] })
    )

    await expect(
      requestImport("account-1", "anycoin", [new File(["x"], "first.csv")], fetchImplementation)
    ).rejects.toMatchObject({
      code: "python_api_contract_error",
    })
  })
})
