import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

describe("version 0.1 Python boundary acceptance", () => {
  it("keeps snapshot workflow transport server-only and generated", async () => {
    const client = await source("src/modules/python-api/server/client.ts")
    const token = await source("src/modules/python-api/server/internal-token.ts")
    const contract = await source("src/modules/python-api/snapshot-workflow-contract.ts")

    expect(client).toContain('import "server-only"')
    expect(token).toContain('import "server-only"')
    expect(contract).toContain('from "@/generated/python-api"')
    expect(client).not.toContain("@/lib/prisma")
  })

  it("has no account or import workflow adapter in the implemented Python bridge", async () => {
    const workflow = await source("src/modules/python-api/server/snapshot-workflow.ts")
    const client = await source("src/modules/python-api/server/client.ts")
    const combined = `${workflow}\n${client}`

    expect(combined).not.toContain("/api/v1/accounts/{account_id}/imports")
    expect(combined).not.toContain('"/api/v1/accounts"')
    expect(combined).not.toContain("runAccount")
    expect(combined).not.toContain("runImport")
  })

  it("keeps current portfolio and dashboard finance on the accepted workflow routes", async () => {
    const portfolio = await source("src/modules/portfolio/snapshot-page-client.ts")
    const dashboard = await source("src/modules/dashboard/snapshot-dashboard-client.ts")

    expect(portfolio).toContain("/api/snapshot-workflow/portfolio")
    expect(dashboard).toContain("/api/snapshot-workflow/dashboard")
    expect(portfolio).not.toContain("PYTHON_BACKEND_URL")
    expect(dashboard).not.toContain("PYTHON_BACKEND_URL")
  })
})
