import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

import {
  buildPortfolioHistoryChartPoints,
  portfolioHistoryInteractionPoint,
  reducePortfolioHistoryInteraction,
} from "./portfolio-history-chart"
import type { SnapshotPortfolioHistoryPoint } from "@/modules/portfolio/snapshot-history-contract"

const POINTS: readonly SnapshotPortfolioHistoryPoint[] = [
  {
    timestamp: "2036-01-01T00:00:00.000",
    resolutionMinutes: 1440,
    cashValue: "10.000000",
    investmentValue: "0.000000",
    investmentCostBasis: "0.000000",
    netInvestedValue: "8.000000",
    liabilitiesValue: "5.000000",
    netWorthValue: "-50.123456",
  },
  {
    timestamp: "2036-01-02T00:00:00.000",
    resolutionMinutes: 720,
    cashValue: "20.000000",
    investmentValue: "123.456789",
    investmentCostBasis: "100.000000",
    netInvestedValue: "110.000000",
    liabilitiesValue: "0.000000",
    netWorthValue: "143.456789",
  },
]

describe("generation portfolio history chart", () => {
  it("previews on hover, restores current on leave, and gives a pin priority until the next click", () => {
    const first = POINTS[0] as SnapshotPortfolioHistoryPoint
    const second = POINTS[1] as SnapshotPortfolioHistoryPoint
    const empty = { pinnedPoint: null, previewPoint: null }

    const previewed = reducePortfolioHistoryInteraction(empty, { type: "preview", point: first })
    expect(portfolioHistoryInteractionPoint(previewed)).toBe(first)

    const left = reducePortfolioHistoryInteraction(previewed, { type: "leave" })
    expect(portfolioHistoryInteractionPoint(left)).toBeNull()

    const pinned = reducePortfolioHistoryInteraction(previewed, {
      type: "toggle-pin",
      point: first,
    })
    expect(portfolioHistoryInteractionPoint(pinned)).toBe(first)
    const ignoredHover = reducePortfolioHistoryInteraction(pinned, {
      type: "preview",
      point: second,
    })
    expect(ignoredHover).toBe(pinned)
    expect(portfolioHistoryInteractionPoint(ignoredHover)).toBe(first)

    const released = reducePortfolioHistoryInteraction(ignoredHover, {
      type: "toggle-pin",
      point: second,
    })
    expect(released.pinnedPoint).toBeNull()
    expect(portfolioHistoryInteractionPoint(released)).toBe(second)
    expect(
      portfolioHistoryInteractionPoint(
        reducePortfolioHistoryInteraction(released, { type: "leave" })
      )
    ).toBeNull()
  })

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
    expect(points.map((point) => point.comparisonExactValue)).toEqual(["0.000000", "100.000000"])
    expect(points.every((point) => point.comparisonLabel === "Investováno")).toBe(true)
  })

  it("compares net worth with deposits rather than investment cost basis", () => {
    const points = buildPortfolioHistoryChartPoints(POINTS, "netWorth")

    expect(points.map((point) => point.comparisonExactValue)).toEqual(["8.000000", "110.000000"])
    expect(points.every((point) => point.comparisonLabel === "Vložené prostředky")).toBe(true)
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
    expect(component).toContain("<ComposedChart")
    expect(component).not.toContain("<AreaChart")
    expect(component).toContain('strokeDasharray="6 5"')
    expect(component).toContain("hasComparison")
    expect(component).toContain("showComparison")
    expect(component).toContain("Investováno")
    expect(component).not.toContain("connectNulls")
    expect(projection).toContain("point.investmentCostBasis ?? null")
    expect(component).toContain("Rozlišení bodu: {point.resolutionLabel}")
    expect(component).toContain("Rozlišení celého grafu:")
    expect(component).toContain("Pro zvolené období zatím nejsou dostupné žádné snapshoty.")
    expect(component).not.toMatch(/CZK|Kč|Czk/)
  })
})
