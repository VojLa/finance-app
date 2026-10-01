import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

import { sortSnapshotHoldingRows, type SnapshotHoldingRow } from "./snapshot-holdings-table"

function row(key: string, overrides: Partial<SnapshotHoldingRow> = {}): SnapshotHoldingRow {
  return {
    key,
    listingId: key,
    symbol: key,
    quantity: "1.0000000000",
    value: "1.000000",
    costBasis: "1.0000000000",
    unrealizedPnlPct: "0.0000",
    allocationPct: "1.0000",
    ...overrides,
  }
}

describe("SnapshotHoldingsTable", () => {
  it("sorts supported numeric columns exactly in both directions and keeps missing values last", () => {
    const rows = [
      row("large", { value: "9007199254740993.000000", quantity: "2.0000000000" }),
      row("close", { value: "9007199254740992.999999", quantity: "1.0000000001" }),
      row("missing", { value: "0.000001", costBasis: undefined, unrealizedPnlPct: undefined }),
    ]

    expect(
      sortSnapshotHoldingRows(rows, { key: "value", direction: "ascending" }).map(
        (item) => item.key
      )
    ).toEqual(["missing", "close", "large"])
    expect(
      sortSnapshotHoldingRows(rows, { key: "quantity", direction: "descending" }).map(
        (item) => item.key
      )
    ).toEqual(["large", "close", "missing"])
    expect(
      sortSnapshotHoldingRows(rows, { key: "costBasis", direction: "ascending" }).at(-1)?.key
    ).toBe("missing")
    expect(
      sortSnapshotHoldingRows(rows, { key: "unrealizedPnlPct", direction: "descending" }).at(-1)
        ?.key
    ).toBe("missing")
  })

  it("sorts instruments and allocation without mutating input", () => {
    const rows = [
      row("b", { symbol: "BBB", allocationPct: "5.0000" }),
      row("a", { symbol: "AAA", allocationPct: "95.0000" }),
    ]
    const before = JSON.stringify(rows)

    expect(
      sortSnapshotHoldingRows(rows, { key: "symbol", direction: "ascending" }).map(
        (item) => item.symbol
      )
    ).toEqual(["AAA", "BBB"])
    expect(
      sortSnapshotHoldingRows(rows, { key: "allocationPct", direction: "descending" }).map(
        (item) => item.symbol
      )
    ).toEqual(["AAA", "BBB"])
    expect(JSON.stringify(rows)).toBe(before)
  })

  it("keeps a fixed five-row viewport and opens the full list in a dialog", async () => {
    const source = await readFile(
      path.join(process.cwd(), "src/modules/portfolio/SnapshotHoldingsTable.tsx"),
      "utf8"
    )

    expect(source).toContain("const VISIBLE_ROWS = 5")
    expect(source).toContain('className="flex h-[344px] flex-col"')
    expect(source).toContain("sortedRows.slice(0, VISIBLE_ROWS)")
    expect(source).toContain("Zobrazit vše ({sortedRows.length})")
    expect(source).toContain('aria-haspopup="dialog"')
    expect(source).toContain('aria-sort={sort.key === header.key ? sort.direction : "none"}')
  })
})
