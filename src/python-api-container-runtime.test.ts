import { readFile } from "node:fs/promises"
import path from "node:path"
import { describe, expect, it } from "vitest"

const ROOT = process.cwd()

describe("Python API container migration runtime", () => {
  it("includes only the required migration client and guarded policy evidence", async () => {
    const dockerfile = await readFile(path.join(ROOT, "backend/python/Dockerfile"), "utf8")

    expect(dockerfile).toMatch(/apt-get update/)
    expect(dockerfile).toMatch(/apt-get install --yes --no-install-recommends postgresql-client/)
    expect(dockerfile).toMatch(/rm -rf \/var\/lib\/apt\/lists\/\*/)
    expect(dockerfile).toContain("COPY package.json /app/package.json")
    expect(dockerfile).toContain("COPY prisma/migrations /app/prisma/migrations")
    expect(dockerfile).toContain("COPY .github/workflows /app/.github/workflows")
    expect(dockerfile).not.toMatch(/COPY\s+\.env(?:\s|$)/)
  })
})
