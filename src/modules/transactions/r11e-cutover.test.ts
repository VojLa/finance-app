import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

describe("R11-E transaction and category cutover", () => {
  it("keeps both Next routes as session and transport adapters only", async () => {
    for (const route of ["src/app/api/transactions/route.ts", "src/app/api/categories/route.ts"]) {
      const content = await source(route)
      expect(content).toContain("getServerSession(authOptions)")
      expect(content).toContain("normalizeAdapterError")
      expect(content).toMatch(/createPython(?:Transaction|Category)Api/)
      expect(content).not.toMatch(/@\/lib\/prisma|prisma\.|assertAccountAccess|CategoryRule/)
      expect(content).not.toMatch(/toCzk|Decimal|reportingAmount|canonical|snapshot/i)
    }
  })

  it("derives browser DTOs from generated OpenAPI contracts", async () => {
    for (const contract of [
      "src/modules/transactions/transaction-contract.ts",
      "src/modules/categories/category-contract.ts",
    ]) {
      const content = await source(contract)
      expect(content).toContain('import type { components } from "@/generated/python-api"')
      expect(content).not.toMatch(/interface |\{\s*id:/)
    }
  })

  it("keeps exact amount strings until presentation and supplies idempotency keys", async () => {
    const page = await source("src/app/transactions/page.tsx")
    expect(page).toContain("amount: createForm.amount")
    expect(page).toContain("amount: editForm.amount")
    expect(page).toContain("Math.abs(Number(tx.amount))")
    expect(page).toContain("crypto.randomUUID()")
    expect(page).not.toMatch(/parseFloat|parseInt|@\/lib\/prisma/)
  })

  it("uses the generated category client and idempotent create command", async () => {
    const page = await source("src/app/categories/page.tsx")
    expect(page).toContain("requestCategories")
    expect(page).toContain("createCategory")
    expect(page).toContain("updateCategory")
    expect(page).toContain("deleteCategory")
    expect(page).toContain("idempotencyKey: crypto.randomUUID()")
    expect(page).not.toMatch(/@\/lib\/prisma|fetch\(/)
  })

  it("publishes exact string amounts in the generated schema", async () => {
    const generated = await source("src/generated/python-api.ts")
    const responseStart = generated.indexOf("TransactionResponse:")
    const response = generated.slice(responseStart, responseStart + 1200)
    expect(response).toMatch(/amount: string/)
  })
})
