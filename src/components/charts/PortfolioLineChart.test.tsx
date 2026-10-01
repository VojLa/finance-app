import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

import { buildPortfolioHistoryChartPoints } from "./portfolio-history-chart"
import type { SnapshotPortfolioHistoryPoint } from "@/modules/portfolio/snapshot-history-contract"

const POINTS: readonly SnapshotPortfolioHistoryPoint[] = [
  {
    timestamp: "2036-01-01T00:00:00.000",
    resolutionMinutes: 1440,
    cashValue: "10.000000",
    investmentValue: "0.000000",
    liabilitiesValue: "5.000000",
    netWorthValue: "-50.123456",
  },
  {
    timestamp: "2036-01-02T00:00:00.000",
    resolutionMinutes: 720,
    cashValue: "20.000000",
    investmentValue: "123.456789",
    liabilitiesValue: "0.000000",
    netWorthValue: "143.456789",
  },
]

describe("generation portfolio history chart", () => {
  it("uses exact net worth strings and presentation labels without mutating input", () => {
    const before = JSON.stringify(POINTS)

    const points = buildPortfolioHistoryChartPoints(POINTS, "netWorth")

    expect(points.map((point) => point.exactValue)).toEqual(["-50.123456", "143.456789"])
    expect(points[0]?.displayValue).toBe(-50.123456)
    expect(points[0]?.dateLabel).toMatch(/1/)
    expect(points.map((point) => point.resolutionLabel)).toEqual(["1 d", "12 h"])
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
        Array.from({ length: 480 }, () => POINTS[0] as SnapshotPortfolioHistoryPoint),
        "investments"
      )
    ).toHaveLength(480)
  })

  it("keeps exact tooltip authority and approved chart-only numeric conversions", async () => {
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
    expect(source.match(/\bNumber\s*\(/g)).toHaveLength(2)
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
    expect(component).toContain("Vložené prostředky")
    expect(component).toContain("const [showNetInvested, setShowNetInvested] = useState(true)")
    expect(component).toContain('strokeDasharray="6 5"')
    expect(component).toContain("point.netInvestedValue !== undefined")
    expect(component).toContain("Rozlišení bodu: {point.resolutionLabel}")
    expect(component).toContain("Preferované rozlišení:")
    expect(component).toContain("Pro zvolené období zatím nejsou dostupné žádné snapshoty.")
    expect(component).not.toMatch(/CZK|Kč|Czk/)
  })
})
