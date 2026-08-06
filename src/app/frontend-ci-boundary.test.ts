import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const WORKFLOW = path.join(process.cwd(), ".github/workflows/frontend.yml")

async function workflow(): Promise<string> {
  return readFile(WORKFLOW, "utf8")
}

describe("Frontend GitHub Actions boundary", () => {
  it("runs every required deterministic gate for frontend changes", async () => {
    const source = await workflow()

    expect(source).toContain("name: Frontend")
    expect(source).toContain('      - "src/**"')
    expect(source).toContain("runs-on: ubuntu-24.04")
    expect(source).toContain("contents: read")
    expect(source).toContain("actions/checkout@v4")
    expect(source).toContain("actions/setup-node@v4")
    expect(source).toContain("actions/setup-python@v5")
    expect(source).toContain("astral-sh/setup-uv@v6")
    for (const command of [
      "uv sync --frozen --extra dev",
      "npm ci",
      "npm run db:generate",
      "npm run api:python:check",
      "npm test",
      "npm run lint",
      "npx tsc --noEmit",
      "npm run db:validate",
      "git diff --check",
      'test -z "$(git status --porcelain)"',
    ]) {
      expect(source).toContain(command)
    }
  })

  it("has ref-scoped cancellation and no weakened or stateful gate", async () => {
    const source = await workflow()

    expect(source).toContain("group: frontend-${{ github.workflow }}-${{ github.ref }}")
    expect(source).toContain("cancel-in-progress: true")
    expect(source).not.toMatch(
      /continue-on-error|npm audit fix|\bnpm run dev\b|\bnext dev\b|localhost:3010|\|\|\s*true/
    )
    expect(source).not.toMatch(/\bauto-merge\b/)
  })
})
