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

describe("R4 import call-graph boundaries", () => {
  it("globally inventories every production import route and keeps used routes thin", async () => {
    const routes = (await filesBelow("src/app/api/import"))
      .filter((file) => file.endsWith("/route.ts") || file.endsWith("import/route.ts"))
      .sort()
    expect(routes).toEqual([
      "src/app/api/import/anycoin/route.ts",
      "src/app/api/import/raiffeisenbank/preview/route.ts",
      "src/app/api/import/raiffeisenbank/route.ts",
      "src/app/api/import/route.ts",
      "src/app/api/import/status/route.ts",
      "src/app/api/import/trading212/route.ts",
    ])

    const usedRoutes = routes.filter((route) => !route.includes("/preview/"))
    for (const route of usedRoutes) {
      const content = await source(route)
      expect(content).not.toMatch(
        /importCsvFilesAsync|DuplicateImportError|@\/modules\/imports["']|@\/imports\/utils\/api|@\/lib\/prisma|file\.text\(|prisma\.|userId/
      )
      expect(content).toMatch(/handleImportPost|handleImportStatus/)
    }
  })

  it("proves the legacy preview route is not reachable from any production page", async () => {
    const pages = (await filesBelow("src/app")).filter(
      (file) => /\/page\.tsx$/.test(file) && !file.includes("/api/")
    )
    const consumers = await Promise.all(pages.map(source))
    expect(consumers.join("\n")).not.toContain("/api/import/raiffeisenbank/preview")
    expect(await source("src/app/import/page.tsx")).not.toMatch(
      /preview|\/api\/import\/raiffeisenbank/
    )
  })

  it("keeps binary hashing and all eight generated paths in the server-only client", async () => {
    const api = await source("src/modules/imports/python/import-api.ts")
    const contract = await source("src/modules/imports/python/import-contract.ts")
    const transport = await source("src/modules/python-api/server/transport.ts")

    expect(api).toContain('import "server-only"')
    expect(api).toContain('from "@/generated/python-api"')
    expect(contract).toContain('from "@/generated/python-api"')
    expect(api).toContain('createHash("sha256").update(input.bytes).digest("hex")')
    expect(api).toContain('"application/octet-stream"')
    expect(transport).toContain('requestedContentType === "application/octet-stream"')
    for (const suffix of [
      "/imports",
      "/file",
      "/parse",
      "/normalize",
      "/deduplicate",
      "/classify",
      "/post",
    ]) {
      expect(api).toContain(suffix)
    }
    expect(api).toContain("getImportBatch")
  })

  it("keeps token issuance, identity and raw Python bodies server-side", async () => {
    const browser = await source("src/modules/imports/python/import-client.ts")
    const route = await source("src/modules/imports/python/import-route.ts")
    const api = await source("src/modules/imports/python/import-api.ts")

    expect(browser).not.toMatch(
      /internal-token|INTERNAL_AUTH_SECRET|PYTHON_BACKEND_URL|Authorization|Cookie|jose/
    )
    expect(route).not.toMatch(/request\.headers|get\(["']userId/)
    expect(api).not.toMatch(/console\.|raw_import_row/)
    expect(route).toContain("summarizeImportFiles")
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
})
