import { readFile } from "node:fs/promises"

import { describe, expect, it } from "vitest"

describe("durable import page", () => {
  it("polls persisted jobs with bounded backoff and never cancels server work", async () => {
    const source = await readFile("src/app/import/page.tsx", "utf8")
    expect(source).toContain("localStorage")
    expect(source).toContain("importPollDelayMs")
    expect(source).toContain("requestImportJob")
    expect(source).toContain("retryImportJob")
    expect(source).toContain("startNewImport")
    expect(source).toContain("Nový import")
    expect(source).toContain("clearPersistedImportJob(localStorage, persistedRecord)")
    expect(source).toContain("acceptJob(acceptance.job)")
    expect(source).toContain("Některé soubory nebyly zařazeny do nového importu")
    expect(source).toContain("beginImportPoll")
    expect(source).toContain("finishImportPoll")
    expect(source).toContain("BACKGROUND_NOTICE_MS = 5_000")
    expect(source).not.toContain("AbortController")
    expect(source).not.toContain("requestImportFinalization")
  })

  it("shows durable state and refresh signal only after completion", async () => {
    const source = await readFile("src/app/import/page.tsx", "utf8")
    expect(source).toContain('status: "background"')
    expect(source).toContain('status: "completed"')
    expect(source).toContain('status: "failed"')
    expect(source).toContain("publishImportCompleted")
    expect(source).toContain("state.job.progress.phase")
    expect(source).toContain("state.job.attempt_count")
    expect(source).toContain("state.job.max_attempts")
  })

  it("shows actionable liability guidance only for the exact waiting-input code", async () => {
    const source = await readFile("src/app/import/page.tsx", "utf8")
    const normalizedSource = source.replace(/\s+/g, " ")
    expect(source).toContain('job.error?.code === "import_liability_balance_required"')
    expect(source).toContain('href="/accounts"')
    expect(source).toContain("zadej aktuální zůstatek")
    expect(normalizedSource).toContain("automaticky pokračuje ve stejném zpracování")
  })
})
