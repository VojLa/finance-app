const PERCENTAGE = /^(?:0|[1-9]\d{0,2})\.(\d{4})$/
const OWN_SLICE_THRESHOLD = 50_000n
const MAX_OWN_SLICES = 5

export type SnapshotAllocationItem = Readonly<{
  key: string
  name: string
  allocationPct: string
}>

export type SnapshotAllocationExactSlice = Readonly<{
  key: string
  name: string
  exactAllocation: string
  members: readonly SnapshotAllocationItem[]
}>

function percentageUnits(value: string): bigint {
  const match = PERCENTAGE.exec(value)
  if (!match) throw new TypeError("Snapshot allocation percentage is not canonical.")
  return BigInt(value.slice(0, value.indexOf("."))) * 10_000n + BigInt(match[1])
}

function unitsPercentage(value: bigint): string {
  return `${value / 10_000n}.${(value % 10_000n).toString().padStart(4, "0")}`
}

export function buildSnapshotAllocationSlices(
  items: readonly SnapshotAllocationItem[]
): SnapshotAllocationExactSlice[] {
  const ordered: SnapshotAllocationItem[] = []
  for (const item of items) {
    const itemUnits = percentageUnits(item.allocationPct)
    let index = ordered.length
    while (
      index > 0 &&
      itemUnits > percentageUnits((ordered[index - 1] as SnapshotAllocationItem).allocationPct)
    ) {
      index -= 1
    }
    ordered.splice(index, 0, item)
  }

  const own: SnapshotAllocationExactSlice[] = []
  const other: SnapshotAllocationItem[] = []
  let otherUnits = 0n
  for (const item of ordered) {
    const units = percentageUnits(item.allocationPct)
    if (units >= OWN_SLICE_THRESHOLD && own.length < MAX_OWN_SLICES) {
      own.push({
        key: item.key,
        name: item.name,
        exactAllocation: item.allocationPct,
        members: [item],
      })
    } else {
      other.push(item)
      otherUnits += units
    }
  }
  if (other.length > 0) {
    own.push({
      key: "other",
      name: "Ostatní",
      exactAllocation: unitsPercentage(otherUnits),
      members: other,
    })
  }
  return own
}
