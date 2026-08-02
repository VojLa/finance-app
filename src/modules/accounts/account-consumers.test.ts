import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const CONSUMERS = [
  "src/app/settings/page.tsx",
  "src/app/import/page.tsx",
  "src/app/portfolio/add/page.tsx",
  "src/app/transactions/page.tsx",
]

describe("typed account collection consumers", () => {
  it.each(CONSUMERS)("%s uses the typed client and handles safe load errors", async (file) => {
    const source = await readFile(path.join(process.cwd(), file), "utf8")

    expect(source).toContain("requestAccounts()")
    expect(source).toContain("AccountClientError")
    expect(source).not.toContain('fetch("/api/accounts")')
  })

  it("settings uses Python membership fields and no legacy sharing DTO", async () => {
    const source = await readFile(path.join(process.cwd(), "src/app/settings/page.tsx"), "utf8")

    expect(source).toContain("account.relationType")
    expect(source).toContain("accountRoleLabel(a.role)")
    expect(source).toContain('status: "loading"')
    expect(source).toContain('status: "ready"')
    expect(source).toContain('status: "empty"')
    expect(source).toContain('status: "error"')
    expect(source).not.toMatch(/\.isShared\b|shareRole|interface SharedAccount/)
  })

  it("import, portfolio-add, and transactions distinguish load errors from empty lists", async () => {
    for (const file of CONSUMERS.slice(1)) {
      const source = await readFile(path.join(process.cwd(), file), "utf8")
      expect(source).toContain("AccountClientError")
      expect(source).toContain("Účty se nepodařilo načíst.")
    }

    const importSource = await readFile(path.join(process.cwd(), "src/app/import/page.tsx"), "utf8")
    expect(importSource).toContain('accountLoadState.status === "error"')
    expect(importSource).toContain('accountLoadState.status === "ready"')

    const portfolioAddSource = await readFile(
      path.join(process.cwd(), "src/app/portfolio/add/page.tsx"),
      "utf8"
    )
    expect(portfolioAddSource).toContain('accountLoadState.status === "loading"')
    expect(portfolioAddSource).toContain('accountLoadState.status === "error"')

    const transactionsSource = await readFile(
      path.join(process.cwd(), "src/app/transactions/page.tsx"),
      "utf8"
    )
    expect(transactionsSource).toContain("accountLoadError")
  })
})
