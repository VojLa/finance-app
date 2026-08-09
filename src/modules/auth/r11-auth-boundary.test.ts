import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()

async function source(file: string): Promise<string> {
  return readFile(path.join(ROOT, file), "utf8")
}

describe("R11-C authentication ownership boundary", () => {
  it("keeps production TypeScript auth free of Prisma and password hashing", async () => {
    const files = [
      "src/lib/auth.ts",
      "src/app/api/auth/register/route.ts",
      "src/app/api/auth/password/route.ts",
      "src/modules/auth/server/auth-api.ts",
    ]

    for (const file of files) {
      const content = await source(file)
      expect(content, file).not.toMatch(/@prisma|lib\/prisma|bcryptjs|passwordHash/)
    }
  })

  it("uses generated Python contracts and preserves NextAuth as session owner", async () => {
    const adapter = await source("src/modules/auth/server/auth-api.ts")
    const nextAuth = await source("src/lib/auth.ts")

    expect(adapter).toContain('from "@/generated/python-api"')
    expect(adapter).toContain('"/api/v1/auth/credentials/verify"')
    expect(adapter).toContain('"/api/v1/auth/register"')
    expect(adapter).toContain('"/api/v1/auth/password"')
    expect(nextAuth).toContain('session: { strategy: "jwt" }')
    expect(nextAuth).toContain("authorizeCredentials")
  })
})
