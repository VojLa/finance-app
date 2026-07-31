import { createHash } from "node:crypto"
import { readdir, readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

async function filesBelow(relativeDirectory: string): Promise<string[]> {
  const absoluteDirectory = path.join(ROOT, relativeDirectory)
  const entries = await readdir(absoluteDirectory, { withFileTypes: true })
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const relativePath = path.join(relativeDirectory, entry.name)
      return entry.isDirectory() ? filesBelow(relativePath) : [relativePath]
    })
  )
  return nested.flat()
}

async function sha256(relativePath: string): Promise<string> {
  return createHash("sha256")
    .update(await readFile(path.join(ROOT, relativePath)))
    .digest("hex")
}

describe("snapshot workflow static boundaries", () => {
  it("marks every server adapter TypeScript file as server-only", async () => {
    const files = (await filesBelow("src/modules/python-api/server")).filter((file) =>
      file.endsWith(".ts")
    )

    expect(files.length).toBeGreaterThan(0)
    for (const file of files) {
      expect(await source(file), file).toContain('import "server-only"')
    }
  })

  it("does not import the token issuer from any client component", async () => {
    const files = (await filesBelow("src")).filter(
      (file) => file.endsWith(".ts") || file.endsWith(".tsx")
    )
    for (const file of files) {
      const content = await source(file)
      if (/^\s*["']use client["']/.test(content)) {
        expect(content, file).not.toContain("internal-token")
      }
    }
  })

  it("keeps portfolio/dashboard pages and legacy routes byte-identical to the exact base", async () => {
    await expect(sha256("src/app/portfolio/page.tsx")).resolves.toBe(
      "97a93c7f972b9ba1d9a516711fdb7c7ce68519ff268ede2046eb928938b223d8"
    )
    await expect(sha256("src/app/dashboard/page.tsx")).resolves.toBe(
      "a3223752963889c74416ee55791f73084880e4693d7b39ec48c70beb9128b059"
    )
    await expect(sha256("src/app/api/portfolio/route.ts")).resolves.toBe(
      "a769510a35313674d485505fe3b1178c323b96675a7bad1c87644f164c7653f8"
    )
    await expect(sha256("src/app/api/dashboard/route.ts")).resolves.toBe(
      "018dfe28e81da5b780df309805ae81ff7c83fb35b9ce8b1ba8e33dda264ce9ee"
    )
  })

  it("registers exactly the two bodyless POST-only workflow route modules", async () => {
    for (const route of [
      "src/app/api/snapshot-workflow/portfolio/route.ts",
      "src/app/api/snapshot-workflow/dashboard/route.ts",
    ]) {
      const content = await source(route)
      expect(content).toContain("export async function POST()")
      expect(content).not.toMatch(/export\s+(?:async\s+)?function\s+GET/)
      expect(content).not.toContain("NextRequest")
      expect(content).not.toContain("request.json")
      expect(content).not.toContain("@/lib/prisma")
      expect(content).not.toContain("internal-token")
      expect(content).not.toMatch(/\b(?:Number|parseFloat|parseInt)\s*\(/)
      expect(content).not.toMatch(/\bMath\./)
      expect(content).not.toContain(".toFixed(")
    }
  })

  it("keeps Prisma, prices, FX, financial math, retries, and discovery out of the adapter", async () => {
    const productionFiles = [
      "src/modules/python-api/server/config.ts",
      "src/modules/python-api/server/errors.ts",
      "src/modules/python-api/server/internal-token.ts",
      "src/modules/python-api/server/client.ts",
      "src/modules/python-api/server/snapshot-workflow.ts",
      "src/modules/python-api/snapshot-workflow-contract.ts",
    ]
    const content = (await Promise.all(productionFiles.map((file) => source(file)))).join("\n")
    const workflowContent = await source("src/modules/python-api/server/snapshot-workflow.ts")

    expect(content).not.toMatch(/from\s+["'][^"']*prisma/i)
    expect(content).not.toMatch(/from\s+["'][^"']*(?:price|fx)[^"']*["']/i)
    expect(workflowContent).not.toMatch(/\b(?:Number|parseFloat|parseInt)\s*\(/)
    expect(workflowContent).not.toMatch(/\bMath\./)
    expect(workflowContent).not.toContain(".toFixed(")
    expect(content).not.toMatch(/\blatest\b/i)
    expect(content).not.toMatch(/account discovery/i)
    expect(content).not.toMatch(/\bretry\b/i)
  })

  it("derives all Python HTTP DTO aliases from the generated OpenAPI contract", async () => {
    const contract = await source("src/modules/python-api/snapshot-workflow-contract.ts")
    expect(contract).toContain('import type { components } from "@/generated/python-api"')
    for (const schema of [
      "UserSnapshotRefreshRecalculateResponse",
      "ExactPortfolioSnapshotSetRequest",
      "MultiAccountPortfolioResponse",
      "DashboardSnapshotResponse",
    ]) {
      expect(contract).toContain(`components["schemas"]["${schema}"]`)
    }
    expect(await source("src/generated/python-api.ts")).toMatch(
      /^\/\/ This file is generated\. Do not edit manually\./
    )
  })

  it("wires deterministic generation and server-only environment contracts", async () => {
    const packageJson = JSON.parse(await source("package.json"))
    expect(packageJson.scripts).toMatchObject({
      "api:python:generate": "node scripts/generate-python-api-types.mjs",
      "api:python:check": "node scripts/generate-python-api-types.mjs --check",
    })
    expect(packageJson.dependencies).toMatchObject({
      jose: expect.any(String),
      "openapi-fetch": expect.any(String),
    })
    expect(packageJson.devDependencies).toMatchObject({
      "openapi-typescript": expect.any(String),
    })

    const exampleEnvironment = await source(".env.example")
    for (const line of [
      'PYTHON_BACKEND_URL="http://localhost:8010"',
      'INTERNAL_AUTH_SECRET="development-internal-auth-secret-change-me"',
      'INTERNAL_AUTH_ISSUER="finance-app-next"',
      'INTERNAL_AUTH_AUDIENCE="finance-app-python"',
      'INTERNAL_AUTH_TOKEN_TTL_SECONDS="60"',
      'PYTHON_API_TIMEOUT_MS="30000"',
    ]) {
      expect(exampleEnvironment).toContain(line)
    }

    const compose = await source("docker-compose.yml")
    expect(
      compose.match(/INTERNAL_AUTH_SECRET: development-internal-auth-secret-change-me/g)
    ).toHaveLength(2)
    expect(compose.match(/INTERNAL_AUTH_ISSUER: finance-app-next/g)).toHaveLength(2)
    expect(compose.match(/INTERNAL_AUTH_AUDIENCE: finance-app-python/g)).toHaveLength(2)
    expect(compose).toContain("PYTHON_BACKEND_URL: http://api:8010")
  })

  it("exports OpenAPI from create_app without database or lifespan execution", async () => {
    const exporter = await source("backend/python/scripts/export_openapi.py")
    expect(exporter).toContain("create_app(settings).openapi()")
    expect(exporter).toContain("database_url=None")
    expect(exporter).not.toContain("TestClient")
    expect(exporter).not.toContain("lifespan(")
    expect(exporter).not.toContain("DATABASE_URL")

    const generator = await source("scripts/generate-python-api-types.mjs")
    expect(generator).toContain('argumentsSet.delete("--check")')
    expect(generator).toContain("mkdtemp(")
    expect(generator).toContain("tracked !== temporaryGenerated")
    expect(generator).not.toMatch(/\b(?:diff|cmp)\b/)
  })
})
