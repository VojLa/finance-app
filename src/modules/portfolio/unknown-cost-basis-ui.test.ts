import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

import { buildSnapshotDashboardModel } from "@/modules/dashboard/snapshot-dashboard-model"
import { anycoinIncompleteDashboardSnapshotFixture } from "@/test/dashboard-snapshot-fixture"
import { anycoinIncompletePortfolioSnapshotFixture } from "@/test/portfolio-snapshot-fixture"

import {
  formatSnapshotAmount,
  formatSnapshotDecimal,
  UNAVAILABLE_COST_BASIS_LABEL,
} from "./snapshot-page-format"
import { buildPortfolioPageModel } from "./snapshot-page-model"

async function source(file: string): Promise<string> {
  return readFile(path.join(process.cwd(), file), "utf8")
}

describe("unknown cost-basis presentation", () => {
  it("keeps Anycoin quantity and value visible while marking cost and P/L unavailable", async () => {
    const model = buildPortfolioPageModel(anycoinIncompletePortfolioSnapshotFixture())
    const anycoin = model.accounts[1]?.positions[0]?.position
    if (anycoin === undefined) throw new Error("Missing Anycoin fixture position.")

    expect(formatSnapshotDecimal(anycoin.quantity)).toBe("1,0000000000")
    expect(formatSnapshotAmount(anycoin.value, anycoin.valueCurrency)).toBe("40,000000 USD")
    expect(formatSnapshotAmount(anycoin.costBasis, anycoin.costCurrency)).toBe(
      UNAVAILABLE_COST_BASIS_LABEL
    )
    expect(formatSnapshotAmount(anycoin.unrealizedPnl, anycoin.valueCurrency)).toBe(
      UNAVAILABLE_COST_BASIS_LABEL
    )

    const table = await source("src/modules/portfolio/SnapshotHoldingsTable.tsx")
    expect(table).toContain("formatSnapshotDecimal(position.quantity)")
    expect(table).toContain("formatSnapshotAmount(position.value, position.valueCurrency)")
    expect(table).toContain("formatSnapshotAmount(position.costBasis, position.costCurrency)")
    expect(table).toContain("formatSnapshotAmount(position.unrealizedPnl, position.valueCurrency)")
  })

  it("marks incomplete dashboard evidence unavailable without hiding total values", async () => {
    const model = buildSnapshotDashboardModel(anycoinIncompleteDashboardSnapshotFixture())
    const anycoin = model.topPositions.find(({ symbol }) => symbol === "BTC")
    if (anycoin === undefined) throw new Error("Missing Anycoin dashboard position.")

    expect(formatSnapshotAmount(model.summary.totalValue, model.currency)).toBe(
      "999 999 999 999,123456 CZK"
    )
    expect(formatSnapshotAmount(model.summary.investmentCostBasis, model.currency)).toBe(
      UNAVAILABLE_COST_BASIS_LABEL
    )
    expect(formatSnapshotAmount(anycoin.value, anycoin.valueCurrency)).toBe("2,000001 CZK")
    expect(formatSnapshotAmount(anycoin.unrealizedPnl, anycoin.valueCurrency)).toBe(
      UNAVAILABLE_COST_BASIS_LABEL
    )

    for (const file of [
      "src/modules/dashboard/SnapshotSummaryCards.tsx",
      "src/modules/dashboard/SnapshotAccountCards.tsx",
      "src/modules/dashboard/SnapshotTopPositions.tsx",
    ]) {
      expect(await source(file)).toContain("formatSnapshotAmount")
    }
  })
})
