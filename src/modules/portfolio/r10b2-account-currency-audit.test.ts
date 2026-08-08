import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

import { buildSnapshotDashboardModel } from "@/modules/dashboard/snapshot-dashboard-model"
import { dashboardSnapshotFixture } from "@/test/dashboard-snapshot-fixture"
import { portfolioSnapshotFixture } from "@/test/portfolio-snapshot-fixture"
import { buildPortfolioPageModel, selectPortfolioAccountView } from "./snapshot-page-model"

const ROOT = process.cwd()

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(ROOT, relativePath), "utf8")
}

describe("R10-B2 account-currency presentation audit", () => {
  it("keeps aggregate finance primary while selected accounts use companion evidence", () => {
    const data = portfolioSnapshotFixture()
    const model = buildPortfolioPageModel(data)
    const czk = selectPortfolioAccountView(model, "account-a")
    const usd = selectPortfolioAccountView(model, "account-b")

    expect(model.aggregate.currency).toBe("EUR")
    expect(model.aggregate.summary).toBe(data.summary)
    expect(model.aggregate.positions[0]?.position).toBe(data.aggregatePositions[0]?.position)
    expect(model.aggregate.positions[0]?.position.valueCurrency).toBe("EUR")
    expect(czk?.currency).toBe("CZK")
    expect(czk?.summary).toBe(data.accounts[0]?.summary)
    expect(czk?.positions[0]?.position.valueCurrency).toBe("CZK")
    expect(usd?.currency).toBe("USD")
    expect(usd?.positions[0]?.position.costCurrency).toBe("USD")
  })

  it("keeps dashboard global CZK and presents the foreign account card in USD", () => {
    const model = buildSnapshotDashboardModel(dashboardSnapshotFixture)
    const foreign = model.accounts.find((account) => account.accountId === "account-z")

    expect(model.currency).toBe("CZK")
    expect(model.summary).toBe(dashboardSnapshotFixture.summary)
    expect(model.topPositions).toBe(dashboardSnapshotFixture.topPositions)
    expect(foreign?.accountCurrency).toBe("USD")
    expect(foreign?.outputCurrency).toBe("USD")
    expect(foreign?.primarySnapshotId).toBe("snapshot-z")
    expect(foreign?.snapshotId).toBe("snapshot-z-usd")
  })

  it("contains no client-side finance conversion, FX lookup, or account-switch request", async () => {
    const files = await Promise.all(
      [
        "src/modules/portfolio/snapshot-page-model.ts",
        "src/modules/dashboard/snapshot-dashboard-model.ts",
        "src/modules/dashboard/SnapshotAccountCards.tsx",
      ].map(source)
    )
    const content = files.join("\n")

    expect(content).not.toMatch(/\b(?:Number|parseFloat|parseInt)\s*\(/)
    expect(content).not.toMatch(/\bMath\./)
    expect(content).not.toContain(".toFixed(")
    expect(content).not.toContain("/api/rates")
    expect(content).not.toMatch(/exchangeRate|latest FX|Prisma/i)
    expect(files[0]).not.toMatch(/\bfetch\s*\(/)
    expect(files[2]).toContain("account.accountCurrency")
  })

  it("pins primary manifest lineage separately from presentation lineage", async () => {
    const workflow = await source("src/modules/python-api/server/snapshot-workflow.ts")

    expect(workflow).toContain("account.primarySnapshotId !== selector.snapshotId")
    expect(workflow).not.toContain("account.snapshotId !== selector.snapshotId")
  })
})
