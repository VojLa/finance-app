export type SnapshotHoldingSortKey =
  | "symbol"
  | "quantity"
  | "value"
  | "costBasis"
  | "unrealizedPnlPct"
  | "allocationPct"
export type SnapshotHoldingSortDirection = "ascending" | "descending"
export type SnapshotHoldingRow = Readonly<{
  key: string
  listingId: string
  symbol: string
  quantity: string
  value: string
  costBasis: string | undefined
  unrealizedPnlPct: string | undefined
  allocationPct: string
}>
export type SnapshotHoldingSort = Readonly<{
  key: SnapshotHoldingSortKey
  direction: SnapshotHoldingSortDirection
}>

const DECIMAL = /^([+-]?)(\d+)(?:\.(\d+))?$/

function compareExactDecimals(left: string, right: string): number {
  const leftMatch = DECIMAL.exec(left)
  const rightMatch = DECIMAL.exec(right)
  if (!leftMatch || !rightMatch) return left.localeCompare(right, "cs")
  const normalize = (match: RegExpExecArray) => {
    const integer = (match[2] ?? "0").replace(/^0+(?=\d)/, "")
    const fraction = (match[3] ?? "").replace(/0+$/, "")
    const zero = integer === "0" && fraction.length === 0
    return { negative: match[1] === "-" && !zero, integer, fraction }
  }
  const a = normalize(leftMatch)
  const b = normalize(rightMatch)
  if (a.negative !== b.negative) return a.negative ? -1 : 1
  let magnitude = a.integer.length - b.integer.length
  if (magnitude === 0) magnitude = a.integer.localeCompare(b.integer)
  if (magnitude === 0) {
    const length = a.fraction.length > b.fraction.length ? a.fraction.length : b.fraction.length
    magnitude = a.fraction.padEnd(length, "0").localeCompare(b.fraction.padEnd(length, "0"))
  }
  return a.negative ? -magnitude : magnitude
}

export function sortSnapshotHoldingRows(
  rows: readonly SnapshotHoldingRow[],
  sort: SnapshotHoldingSort
): SnapshotHoldingRow[] {
  const compare = (left: SnapshotHoldingRow, right: SnapshotHoldingRow) => {
    if (sort.key !== "symbol") {
      const leftValue = left[sort.key]
      const rightValue = right[sort.key]
      if (leftValue === undefined || rightValue === undefined) {
        if (leftValue === undefined && rightValue === undefined)
          return left.key.localeCompare(right.key, "cs")
        return leftValue === undefined ? 1 : -1
      }
    }
    const result =
      sort.key === "symbol"
        ? left.symbol.localeCompare(right.symbol, "cs", { sensitivity: "base" })
        : compareExactDecimals(left[sort.key] as string, right[sort.key] as string)
    const directed = sort.direction === "ascending" ? result : -result
    return directed !== 0 ? directed : left.key.localeCompare(right.key, "cs")
  }
  // Stable insertion preserves exact decimal ordering without float conversion.
  const ordered: SnapshotHoldingRow[] = []
  for (const row of rows) {
    let index = ordered.length
    while (index > 0 && compare(row, ordered[index - 1] as SnapshotHoldingRow) < 0) index -= 1
    ordered.splice(index, 0, row)
  }
  return ordered
}
