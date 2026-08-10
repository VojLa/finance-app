import { execFileSync, spawnSync } from "node:child_process"
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { afterEach, describe, expect, it } from "vitest"

const repositoryRoot = path.resolve(__dirname, "../../..")
const checker = path.join(repositoryRoot, "scripts", "check-typescript-boundary.mjs")
const temporaryDirectories: string[] = []

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true })
  }
})

describe("TypeScript architecture boundary", () => {
  it("classifies every API route and keeps production TypeScript transport-only", () => {
    expect(() =>
      execFileSync(process.execPath, [checker], {
        cwd: repositoryRoot,
        encoding: "utf8",
        stdio: "pipe",
      })
    ).not.toThrow()
  })

  it("rejects a negative fixture that imports database access", () => {
    const fixtureRoot = mkdtempSync(path.join(tmpdir(), "finance-app-ts-boundary-"))
    temporaryDirectories.push(fixtureRoot)
    const sourceDirectory = path.join(fixtureRoot, "src")
    mkdirSync(sourceDirectory, { recursive: true })
    writeFileSync(
      path.join(sourceDirectory, "unsafe.ts"),
      'import { Client } from "pg"\nexport const client = new Client()\n',
      "utf8"
    )

    const result = spawnSync(process.execPath, [checker, "--root", fixtureRoot, "--scan-only"], {
      encoding: "utf8",
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain("forbidden runtime dependency import 'pg'")
  })

  it("rejects a negative fixture that imports a local business service", () => {
    const fixtureRoot = mkdtempSync(path.join(tmpdir(), "finance-app-ts-service-boundary-"))
    temporaryDirectories.push(fixtureRoot)
    const sourceDirectory = path.join(fixtureRoot, "src")
    mkdirSync(sourceDirectory, { recursive: true })
    writeFileSync(
      path.join(sourceDirectory, "unsafe.ts"),
      'import { calculate } from "@/modules/portfolio/service"\nexport { calculate }\n',
      "utf8"
    )

    const result = spawnSync(process.execPath, [checker, "--root", fixtureRoot, "--scan-only"], {
      encoding: "utf8",
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain(
      "forbidden business/data-layer import '@/modules/portfolio/service'"
    )
  })
})
