import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

describe("version 0.1 current browser boundary inventory", () => {
  it("keeps the historical NOT READY audit immutable while testing current routes", async () => {
    const historical = await source("ChatGPT/audits/0.1-final-acceptance.md")
    const accounts = await source("src/app/api/accounts/route.ts")
    const imports = await source("src/app/api/import/route.ts")
    const importHandler = await source("src/modules/imports/python/import-route.ts")
    const history = await source("src/app/api/portfolio/history/route.ts")

    expect(historical).toContain("B1 account browser cutover")
    expect(historical).toContain("B2 import browser/status/multi-file cutover")
    expect(historical).toContain("B6 portfolio history")
    expect(accounts).toContain("createAccount")
    expect(imports).toContain("handleImportPost")
    expect(importHandler).toContain("runImportCanonicalWorkflow")
    expect(importHandler).toContain("finalizeImportBatches")
    expect(history).toContain("readSnapshotBackedPortfolioHistory")
    expect(`${accounts}\n${imports}\n${importHandler}\n${history}`).not.toMatch(
      /@\/lib\/prisma|importCsvFilesAsync|getPortfolioSnapshotHistory/
    )
  })

  it("contains the three current snapshot-backed browser read routes", async () => {
    const portfolio = await source("src/app/api/snapshot-workflow/portfolio/route.ts")
    const dashboard = await source("src/app/api/snapshot-workflow/dashboard/route.ts")
    const history = await source("src/app/api/portfolio/history/route.ts")

    expect(portfolio).toContain("runPortfolioSnapshotWorkflow")
    expect(dashboard).toContain("runDashboardSnapshotWorkflow")
    expect(history).toContain("readSnapshotBackedPortfolioHistory")
  })

  it("keeps current acceptance independent of unavailable historical Git objects", async () => {
    const currentAcceptance = (
      await Promise.all(
        [
          "src/app/dashboard/dashboard-snapshot-cutover.test.ts",
          "src/app/portfolio/portfolio-snapshot-cutover.test.ts",
          "src/modules/accounts/account-cutover-boundaries.test.ts",
        ].map(source)
      )
    ).join("\n")

    expect(currentAcceptance).not.toContain("execFileSync")
    expect(currentAcceptance).not.toMatch(/\b[0-9a-f]{40}\b/)
  })

  it("records R10-A while leaving version 0.1 remediation open", async () => {
    const roadmap = await source("ChatGPT/steps/0.1-remediation.md")

    expect(roadmap).toContain("0.1-R8 — clean main scenario and frontend CI: implemented")
    expect(roadmap).toContain(
      "0.1-R9 — repeat final acceptance audit: completed — NOT READY after independent"
    )
    expect(roadmap).toContain("0.1-R10-A — multi-file import post-processing closure: implemented")
    expect(roadmap).toContain("0.1-R10-B — account-currency presentation: planned")
    expect(roadmap).toContain("Version 0.1 is not complete")
  })
})
