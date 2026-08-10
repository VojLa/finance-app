import { readFile, readdir } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()

async function source(relativePath: string) {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

async function filesBelow(relativePath: string): Promise<string[]> {
  const absolute = path.join(ROOT, relativePath)
  const entries = await readdir(absolute, { withFileTypes: true })
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const child = path.join(relativePath, entry.name).replaceAll("\\", "/")
      return entry.isDirectory() ? filesBelow(child) : [child]
    })
  )
  return nested.flat()
}

describe("R12 durable import call-graph boundaries", () => {
  it("registers only the create/upload/job status/retry browser routes", async () => {
    const routes = (await filesBelow("src/app/api/import"))
      .filter((file) => file.endsWith("/route.ts") || file.endsWith("import/route.ts"))
      .sort()
    expect(routes).toEqual([
      "src/app/api/import/jobs/[jobId]/retry/route.ts",
      "src/app/api/import/jobs/[jobId]/route.ts",
      "src/app/api/import/route.ts",
    ])

    for (const route of routes) {
      const content = await source(route)
      expect(content).not.toMatch(
        /importCsvFilesAsync|DuplicateImportError|@\/imports\/utils\/api|@\/lib\/prisma|file\.text\(|prisma\./
      )
      expect(content).not.toMatch(
        /parseImportBatch|normalizeImportBatch|deduplicateImportBatch|classifyImportBatch|canonicalPostImportBatch|finalizeImportBatches/
      )
    }
  })

  it("keeps Next.js limited to durable registration, upload, start, status, and retry transport", async () => {
    const api = await source("src/modules/imports/python/import-api.ts")
    const route = await source("src/modules/imports/python/import-route.ts")
    const client = await source("src/modules/imports/python/import-client.ts")
    const contract = await source("src/modules/imports/python/import-contract.ts")
    const active = `${api}\n${route}\n${client}\n${contract}`

    expect(api).toContain('import "server-only"')
    expect(api).toContain('from "@/generated/python-api"')
    expect(api).toContain('"application/octet-stream"')
    for (const operation of [
      "createImportBatch",
      "uploadImportFile",
      "startImportJob",
      "getImportJob",
      "retryImportJob",
    ]) {
      expect(api).toContain(operation)
    }
    expect(route).toContain("createImportBatch")
    expect(route).toContain("uploadImportFile")
    expect(route).toContain("startImportJob")
    expect(client).toContain("requestImport")
    expect(client).toContain("requestImportJob")
    expect(client).toContain("retryImportJob")
    expect(active).not.toMatch(
      /runImportCanonicalWorkflow|async parseImportBatch|async normalizeImportBatch|async deduplicateImportBatch|async classifyImportBatch|async canonicalPostImportBatch|async postImportBatch|async finalizeImportBatches|requestImportFinalization|ImportFinalization|\/finalize/
    )
  })

  it("keeps failed jobs retryable while Python owns processing and publication", async () => {
    const page = await source("src/app/import/page.tsx")
    const route = await source("src/modules/imports/python/import-route.ts")
    const api = await source("src/modules/imports/python/import-api.ts")

    expect(page).toContain("retryImportJob")
    expect(page).toContain("loadLatestPersistedImportJob")
    expect(route).toContain("startImportJob")
    expect(`${page}\n${route}\n${api}`).not.toMatch(
      /sourceOverride|snapshotTimestamp|calculationVersion|holdingSelector|marketRequirements|rebuildHoldings|snapshotRefresh/
    )
  })

  it("keeps token issuance, identity, and raw Python bodies server-side", async () => {
    const browser = await source("src/modules/imports/python/import-client.ts")
    const route = await source("src/modules/imports/python/import-route.ts")
    const api = await source("src/modules/imports/python/import-api.ts")

    expect(browser).not.toMatch(
      /internal-token|INTERNAL_AUTH_SECRET|PYTHON_BACKEND_URL|Authorization|Cookie|jose/
    )
    expect(route).not.toMatch(/request\.headers|get\(["']userId/)
    expect(api).not.toMatch(/console\.|raw_import_row/)
    expect(route).toContain("getServerSession")
    expect(api).toContain("createAuthenticatedPythonTransport")
  })

  it("proves the used browser flow has no TypeScript import-domain owner", async () => {
    const page = await source("src/app/import/page.tsx")
    const client = await source("src/modules/imports/python/import-client.ts")
    const route = await source("src/modules/imports/python/import-route.ts")
    const usedFlow = `${page}\n${client}\n${route}`

    expect(usedFlow).not.toMatch(
      /@\/modules\/imports["']|@\/imports\/|papaparse|parseCsv|importCsvFilesAsync|DuplicateImportError|run-import|import-service|InvestmentEvent|Transaction/
    )
    expect(client).toContain('export const IMPORT_PATH = "/api/import"')
    expect(page).toContain("requestImport")
  })

  it("contains no legacy registry, parser, compatibility barrel, provider route, or finalization route", async () => {
    const productionFiles = (await filesBelow("src")).filter(
      (file) => !file.endsWith(".test.ts") && !file.endsWith(".test.tsx")
    )
    const forbidden = productionFiles.filter((file) =>
      /src\/(?:imports|parsers)\/|src\/modules\/imports\/(?:parsers|import-registry|import-service|run-import|index)\b/.test(
        file
      )
    )
    expect(forbidden).toEqual([])
    expect(productionFiles).not.toContain("src/app/api/import/finalize/route.ts")
    expect(productionFiles).not.toContain("src/app/api/import/status/route.ts")
    expect(productionFiles).not.toContain("src/app/api/import/anycoin/route.ts")
    expect(productionFiles).not.toContain("src/app/api/import/trading212/route.ts")
    expect(productionFiles).not.toContain("src/app/api/import/raiffeisenbank/route.ts")

    const packageJson = await source("package.json")
    expect(packageJson).not.toContain("papaparse")
  })
})
