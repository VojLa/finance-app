import { execFileSync } from "node:child_process"
import { readdir, readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()
const BASE_SHA = "20db8a8b5466957868b8ec4e61bcde3d4f2cf265"

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
  const tracked = execFileSync("git", ["diff", "--name-only", BASE_SHA, "--"], {
    cwd: ROOT,
    encoding: "utf8",
  })
  const untracked = execFileSync("git", ["ls-files", "--others", "--exclude-standard"], {
    cwd: ROOT,
    encoding: "utf8",
  })
  return `${tracked}\n${untracked}`
    .split(/\r?\n/)
    .filter(Boolean)
    .map((file) => file.replaceAll("\\", "/"))
}

describe("version 0.1 production freeze", () => {
  it("changes only audit tests, helpers, and audit documentation", () => {
    for (const file of changedFiles()) {
      const allowed =
        file.startsWith("ChatGPT/audits/") ||
        file.startsWith("backend/python/tests/") ||
        (file.startsWith("src/") && (file.endsWith(".test.ts") || file.endsWith(".test.tsx")))
      expect(allowed, file).toBe(true)
    }
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
    const page = await source("src/app/accounts/page.tsx")
    const route = await source("src/app/api/accounts/route.ts")

    expect(page).toContain('fetch("/api/accounts"')
    expect(route).toContain('from "@/lib/prisma"')
    expect(route).toContain("prisma.account.create")
    expect(route).toContain("members:")
    expect(route).not.toContain("/api/v1/accounts")
  })

  it("records the import frontend blocker for every mandatory source", async () => {
    const page = await source("src/app/import/page.tsx")
    for (const provider of ["raiffeisenbank", "trading212", "anycoin"]) {
      const route = await source(`src/app/api/import/${provider}/route.ts`)
      expect(page).toContain(`/api/import/${provider}`)
      expect(route).toContain('from "@/modules/imports"')
      expect(route).toContain("importCsvFilesAsync")
      expect(route).not.toContain("/api/v1/accounts/")
    }
  })

  it("records that portfolio history is still a legacy Next business read", async () => {
    const route = await source("src/app/api/portfolio/history/route.ts")
    const client = await source("src/modules/portfolio/snapshot-history-client.ts")

    expect(route).toContain("getPortfolioSnapshotHistory")
    expect(route).not.toContain("@/modules/python-api")
    expect(client).toContain("legacy response is chart-only")
    expect(client).toContain("/api/portfolio/history")
  })
})
