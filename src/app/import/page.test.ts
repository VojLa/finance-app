import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

import { IMPORT_SOURCE_OPTIONS } from "@/modules/imports/python/import-sources"

const PAGE_PATH = path.join(process.cwd(), "src/app/import/page.tsx")

describe("import page Python cutover", () => {
  it("uses one typed browser import client and no provider-specific route", async () => {
    const source = await readFile(PAGE_PATH, "utf8")

    expect(source).toContain("requestImport(accountId, source.value, files)")
    expect(source).toContain('from "@/modules/imports/python/import-client"')
    expect(source).not.toMatch(/\/api\/import\/(?:raiffeisenbank|trading212|anycoin|status)/)
    expect(source).not.toContain("/preview")
    expect(source).not.toContain("fetch(")
  })

  it("keeps source metadata transport-neutral with exact account filters", () => {
    expect(IMPORT_SOURCE_OPTIONS).toEqual([
      {
        value: "raiffeisenbank",
        label: "Raiffeisenbank",
        accepts: ["bank"],
      },
      {
        value: "trading212",
        label: "Trading 212",
        accepts: ["broker"],
      },
      {
        value: "anycoin",
        label: "Anycoin",
        accepts: ["exchange"],
      },
    ])
    expect(JSON.stringify(IMPORT_SOURCE_OPTIONS)).not.toContain("endpoint")
  })

  it("has explicit account and import state unions including safe partial failure", async () => {
    const source = await readFile(PAGE_PATH, "utf8")

    expect(source).toContain('{ status: "loading" }')
    expect(source).toContain('{ status: "ready"; accounts:')
    expect(source).toContain('{ status: "error"; message: string }')
    expect(source).toContain('{ status: "idle" }')
    expect(source).toContain('{ status: "uploading"; completed: number; total: number }')
    expect(source).toContain('{ status: "recovering"; result: ImportSummary }')
    expect(source).toContain('{ status: "completed"; result: ImportSummary }')
    expect(source).toContain('{ status: "error"; message: string; partial?: ImportSummary }')
    expect(source).toContain("safeError.partial")
  })

  it("retains ordered multi-file results, review counts, duplicate and reset UX", async () => {
    const source = await readFile(PAGE_PATH, "utf8")

    expect(source).toContain("result.files.map")
    expect(source).toContain("file.rowsNeedsReview")
    expect(source).toContain("result.duplicateFiles")
    expect(source).toContain("file.lastSuccessfulStage")
    expect(source).toContain("handleReset")
    expect(source).toContain('setPageState({ status: "idle" })')
  })

  it("offers persisted-batch recovery without uploading files again", async () => {
    const source = await readFile(PAGE_PATH, "utf8")
    const recovery = source.slice(
      source.indexOf("async function handleFinalizationRetry"),
      source.indexOf("const isBusy")
    )

    expect(source).toContain("requiresImportFinalizationRecovery")
    expect(source).toContain("Zkusit dokončit aktualizaci")
    expect(source).toContain("Data byla zaúčtována")
    expect(recovery).toContain("recoverableBatchIds(result)")
    expect(recovery).toContain("requestImportFinalization(accountId, batchIds)")
    expect(recovery).not.toContain("requestImport(")
    expect(recovery).not.toContain("File")
    expect(recovery).not.toContain("FormData")
  })

  it("has no preview request, status polling, timer, legacy parser, or raw account fetch", async () => {
    const source = await readFile(PAGE_PATH, "utf8")

    expect(source).not.toMatch(
      /preview|activeBatchIds|setInterval|setTimeout|importCsvFilesAsync|DuplicateImportError|file\.text\(|@\/lib\/prisma/
    )
    expect(source).toContain("requestAccounts()")
    expect(source).toContain("initialAccountLoadStarted.current")
  })

  it("does not issue an import request from an invalid page state", async () => {
    const source = await readFile(PAGE_PATH, "utf8")
    const guard = source.slice(
      source.indexOf("async function handleImport()"),
      source.indexOf('setPageState({ status: "uploading"')
    )

    expect(guard).toContain('accountLoadState.status !== "ready"')
    expect(guard).toContain("accountId.length === 0")
    expect(guard).toContain("files.length === 0")
    expect(guard).toContain('pageState.status === "uploading"')
    expect(guard).toContain("return")
  })

  it("guards one account request without cancelling the Strict Mode replay", async () => {
    const source = await readFile(PAGE_PATH, "utf8")

    expect(source).toContain("if (initialAccountLoadStarted.current) return")
    expect(source).toContain("initialAccountLoadStarted.current = true")
    expect(source).not.toContain("active = false")
  })
})
