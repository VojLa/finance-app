import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

import { buildPortfolioHistoryChartPoints } from "./portfolio-history-chart"
import type { SnapshotPortfolioHistoryPoint } from "@/modules/portfolio/snapshot-history-contract"

const POINTS: readonly SnapshotPortfolioHistoryPoint[] = [
  {
    timestamp: "2036-01-01T00:00:00.000",
    cashValue: "10.000000",
    investmentValue: "0.000000",
    liabilitiesValue: "5.000000",
    netWorthValue: "-50.123456",
  },
  {
    timestamp: "2036-01-02T00:00:00.000",
    cashValue: "20.000000",
    investmentValue: "123.456789",
    liabilitiesValue: "0.000000",
    netWorthValue: "143.456789",
  },
]

describe("snapshot-backed portfolio history chart", () => {
  it("uses exact net worth strings and presentation labels without mutating input", () => {
    const before = JSON.stringify(POINTS)

    const points = buildPortfolioHistoryChartPoints(POINTS, "netWorth")

    expect(points.map((point) => point.exactValue)).toEqual(["-50.123456", "143.456789"])
    expect(points[0]?.displayValue).toBe(-50.123456)
    expect(points[0]?.dateLabel).toMatch(/1/)
    expect(JSON.stringify(POINTS)).toBe(before)
  })

  it("uses exact investment strings including zero", () => {
    const points = buildPortfolioHistoryChartPoints(POINTS, "investments")

    expect(points.map((point) => point.exactValue)).toEqual(["0.000000", "123.456789"])
    expect(points[0]?.displayValue).toBe(0)
  })

  it("supports one point and the response cap", () => {
    expect(buildPortfolioHistoryChartPoints(POINTS.slice(0, 1), "netWorth")).toHaveLength(1)
    expect(
      buildPortfolioHistoryChartPoints(
        Array.from({ length: 512 }, () => POINTS[0] as SnapshotPortfolioHistoryPoint),
        "investments"
      )
    ).toHaveLength(512)
  })

  it("keeps exact tooltip authority and one approved numeric leaf conversion", async () => {
    const component = await readFile(
      path.join(process.cwd(), "src/components/charts/PortfolioLineChart.tsx"),
      "utf8"
    )
    const projection = await readFile(
      path.join(process.cwd(), "src/components/charts/portfolio-history-chart.ts"),
      "utf8"
    )
    const source = `${component}\n${projection}`

    expect(source).toContain("formatSnapshotAmount(point.exactValue, currency)")
    expect(source).toContain("new Date(`${timestamp}Z`)")
    expect(source.match(/\bNumber\s*\(/g)).toHaveLength(1)
    expect(source).toContain(
      "Presentation-only conversion at the Recharts coordinate leaf boundary"
    )
    expect(source).not.toMatch(
      /investedCzk|netDepositsCzk|investmentCostBasisCzk|cashCzk|currentValueCzk|currentCzk/
    )
    expect(source).not.toMatch(
      /\bMath\.|parseFloat|parseInt|toFixed|FX|baseline|\.reduce\(|\.sort\(/
    )
    expect(source).not.toMatch(/netWorthValue\s*[-+]|cashValue\s*[-+]|liabilitiesValue\s*[-+]/)
    expect(component).toContain("Historický vývoj čisté hodnoty")
    expect(component).toContain("Měna historie: {currency}")
    expect(component).toContain("Pro zvolené období zatím nejsou dostupné žádné snapshoty.")
    expect(component).not.toMatch(/CZK|Kč|Czk/)
  })
})
