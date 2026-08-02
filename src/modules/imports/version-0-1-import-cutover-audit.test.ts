import type { NextRequest } from "next/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { getImportContext } from "@/imports/utils/api"
import { importCsvFilesAsync } from "@/modules/imports"
import * as anycoinRoute from "@/app/api/import/anycoin/route"
import * as raiffeisenbankRoute from "@/app/api/import/raiffeisenbank/route"
import * as trading212Route from "@/app/api/import/trading212/route"

vi.mock("@/modules/imports", () => ({
  DuplicateImportError: class DuplicateImportError extends Error {},
  importCsvFilesAsync: vi.fn(),
}))

vi.mock("@/imports/utils/api", () => ({
  getImportContext: vi.fn(),
  handleImportError: vi.fn(),
}))

const context = vi.mocked(getImportContext)
const runImport = vi.mocked(importCsvFilesAsync)

const ROUTES = [
  ["raiffeisenbank", raiffeisenbankRoute.POST],
  ["trading212", trading212Route.POST],
  ["anycoin", anycoinRoute.POST],
] as const

beforeEach(() => {
  vi.clearAllMocks()
})

describe.each(ROUTES)("version 0.1 %s browser import acceptance", (source, post) => {
  it("proves the current route invokes the TypeScript import orchestrator", async () => {
    const file = {
      name: `${source}.csv`,
      text: async () => "header\nvalue\n",
    } as File
    context.mockResolvedValue({
      ok: true,
      accountId: "import-audit-account",
      userId: "import-audit-user",
      file,
      files: [file],
    })
    runImport.mockResolvedValue({
      accepted: true,
      batchIds: [`${source}-batch`],
      files: [],
    })
    const backendFetch = vi.spyOn(globalThis, "fetch")

    const response = await post(
      new Request(`http://next.test/api/import/${source}`, {
        method: "POST",
      }) as NextRequest
    )

    expect(response.status).toBe(200)
    expect(context).toHaveBeenCalledTimes(1)
    expect(runImport).toHaveBeenCalledTimes(1)
    expect(runImport).toHaveBeenCalledWith({
      files: [{ content: "header\nvalue\n", filename: `${source}.csv` }],
      accountId: "import-audit-account",
      userId: "import-audit-user",
      source,
    })
    expect(backendFetch).not.toHaveBeenCalled()
  })
})
