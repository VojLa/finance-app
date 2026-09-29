import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"
import { dashboardSnapshotFixture } from "@/test/dashboard-snapshot-fixture"
import { buildSnapshotDashboardModel } from "./snapshot-dashboard-model"

describe("snapshot dashboard model", () => {
  it("preserves server-owned evidence and top-position ordering", () => {
    const model = buildSnapshotDashboardModel(dashboardSnapshotFixture)

    expect(model).toMatchObject({
      timestamp: dashboardSnapshotFixture.asOf,
      granularity: "current",
      currency: dashboardSnapshotFixture.currency,
      calculationVersion: dashboardSnapshotFixture.calculationVersion,
    })
    expect(model.summary).toBe(dashboardSnapshotFixture.summary)
    expect(model.accounts).toBe(dashboardSnapshotFixture.accounts)
    expect(model.assetTypeAllocations).toBe(dashboardSnapshotFixture.assetTypeAllocations)
    expect(model.topPositions).toBe(dashboardSnapshotFixture.topPositions)
    expect(model.summary.totalValue).toBe("999999999999.123456")
    expect(model.summary.liabilitiesValue).toBe("-789.876545")
    expect(model.summary.realizedPnlValue).toBe("-0.000001")
    expect(model.summary.netDepositsValue).toBe("123456.789012")
    expect(model.accounts.map(({ accountId }) => accountId)).toEqual(["account-z", "account-a"])
    expect(model.accounts[0]?.primaryBaselineSnapshotId).toBe("snapshot-z")
    expect(model.accounts[0]?.baselineSnapshotId).toBe("snapshot-z-usd")
    expect(model.accounts[0]?.accountCurrency).toBe("USD")
    expect(model.accounts[0]?.outputCurrency).toBe("USD")
    expect(model.accounts[0]?.netDepositsValue).toBe("1250.000000")
    expect(model.accounts[1]?.netDepositsValue).toBe("0.000000")
    expect(model.currency).toBe("CZK")
    expect(model.assetTypeAllocations.map(({ assetType }) => assetType)).toEqual([
      "crypto",
      "stock",
    ])
    expect(model.topPositions.map(({ symbol }) => symbol)).toEqual(["ZZZ", "AAA"])
  })

  it("does not reinterpret or reorder exact server-owned position values", () => {
    const fixture = structuredClone(dashboardSnapshotFixture)
    const [zeta, alpha] = fixture.topPositions
    if (zeta === undefined || alpha === undefined) throw new Error("Missing top-position fixture.")
    zeta.value = "900000000000.000001"
    alpha.value = "900000000000.000001"
    alpha.accountId = "account-a"
    alpha.listingId = "listing-a"
    fixture.topPositions = [zeta, alpha]

    const model = buildSnapshotDashboardModel(fixture)

    expect(
      model.topPositions.map(({ accountId, listingId }) => `${accountId}:${listingId}`)
    ).toEqual(["account-z:listing-z", "account-a:listing-a"])
    expect(fixture.topPositions.map(({ accountId }) => accountId)).toEqual([
      "account-z",
      "account-a",
    ])
  })

  it("is deterministic and does not mutate its input", () => {
    const before = structuredClone(dashboardSnapshotFixture)

    expect(buildSnapshotDashboardModel(dashboardSnapshotFixture)).toEqual(
      buildSnapshotDashboardModel(dashboardSnapshotFixture)
    )
    expect(dashboardSnapshotFixture).toEqual(before)
  })

  it("contains no financial aggregation, lookup, or lossy numeric conversion", async () => {
    const content = await readFile(
      path.join(process.cwd(), "src/modules/dashboard/snapshot-dashboard-model.ts"),
      "utf8"
    )

    expect(content).not.toMatch(/\b(?:Number|parseFloat|parseInt)\s*\(/)
    expect(content).not.toMatch(/\bMath\./)
    expect(content).not.toContain(".toFixed(")
    expect(content).not.toContain(".reduce(")
    expect(content).not.toMatch(/\b(?:fetch|Prisma|latest|FX|price)\b/i)
  })
})
