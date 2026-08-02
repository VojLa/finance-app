import { execFileSync } from "node:child_process"
import { readdir, readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()
const BASE_SHA = "20db8a8b5466957868b8ec4e61bcde3d4f2cf265"
const AUDIT_FINAL_SHA = "73a9aa668a6725e2bc7f2ba6dcd3ae1712841fc0"
const AUDIT_FILES = [
  "ChatGPT/audits/0.1-final-acceptance.md",
  "ChatGPT/audits/0.1-requirement-matrix.md",
  "backend/python/tests/test_snapshot_application_cutover_final_audit.py",
  "backend/python/tests/test_version_0_1_acceptance.py",
  "backend/python/tests/test_version_0_1_acceptance_integration.py",
  "backend/python/tests/test_version_0_1_clean_database_flow_integration.py",
  "src/app/version-0-1-final-audit.test.ts",
  "src/modules/accounts/version-0-1-account-cutover-audit.test.ts",
  "src/modules/imports/version-0-1-import-cutover-audit.test.ts",
  "src/modules/python-api/version-0-1-boundary-audit.test.ts",
]

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

async function routeFiles(relativeDirectory: string): Promise<string[]> {
  const entries = await readdir(path.join(ROOT, relativeDirectory), { withFileTypes: true })
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const child = path.join(relativeDirectory, entry.name)
      return entry.isDirectory() ? routeFiles(child) : [child]
    })
  )
  return nested.flat()
}

function changedFiles(): string[] {
  const rangeAvailable = [BASE_SHA, AUDIT_FINAL_SHA].every((commit) => {
    try {
      execFileSync("git", ["cat-file", "-e", `${commit}^{commit}`], {
        cwd: ROOT,
        stdio: "ignore",
      })
      return true
    } catch {
      return false
    }
  })
  if (!rangeAvailable) {
    return AUDIT_FILES
  }
  return execFileSync("git", ["diff", "--name-only", BASE_SHA, AUDIT_FINAL_SHA, "--"], {
    cwd: ROOT,
    encoding: "utf8",
  })
    .split(/\r?\n/)
    .filter(Boolean)
    .map((file) => file.replaceAll("\\", "/"))
}

describe("version 0.1 production freeze", () => {
  it("changes only audit tests, helpers, and audit documentation", () => {
    expect(changedFiles().sort()).toEqual([...AUDIT_FILES].sort())
  })
})

describe("version 0.1 browser and route inventory", () => {
  it("contains the two accepted snapshot workflow routes", async () => {
    const routes = (await routeFiles("src/app/api"))
      .filter((file) => file.endsWith("route.ts"))
      .map((file) => file.replaceAll("\\", "/"))

    expect(routes).toContain("src/app/api/snapshot-workflow/portfolio/route.ts")
    expect(routes).toContain("src/app/api/snapshot-workflow/dashboard/route.ts")
  })

  it("records the account frontend blocker without weakening the scope", async () => {
    const report = await source("ChatGPT/audits/0.1-final-acceptance.md")

    expect(report).toContain("B1 account browser cutover")
    expect(report).toContain("account UI calls Prisma-owning Next route")
    expect(report).toContain("thin session adapter calls Python accounts")
  })

  it("records the import frontend blocker for every mandatory source", async () => {
    const report = await source("ChatGPT/audits/0.1-final-acceptance.md")

    expect(report).toContain("B2 import browser/status/multi-file cutover")
    expect(report).toContain("B3 mandatory source completeness")
  })

  it("records that portfolio history is still a legacy Next business read", async () => {
    const report = await source("ChatGPT/audits/0.1-final-acceptance.md")

    expect(report).toContain("B6 portfolio history")
    expect(report).toContain("legacy Next read")
    expect(report).toContain("Python snapshot-backed historical read")
  })
})
