"use client"

import {
  buildSnapshotAllocationSlices,
  type SnapshotAllocationExactSlice,
  type SnapshotAllocationItem,
} from "./snapshot-allocation-pie"
import { formatSnapshotPercentage } from "./snapshot-page-format"

const COLORS = ["#2563eb", "#059669", "#d97706", "#dc2626", "#7c3aed", "#475569"]

type SnapshotAllocationSegment = SnapshotAllocationExactSlice &
  Readonly<{
    color: string
    offset: number
    value: number
  }>

/** Presentation-only conversion at the SVG coordinate leaf boundary. */
function toChartNumber(slice: SnapshotAllocationExactSlice): number {
  const converted = Number(slice.exactAllocation)
  const roundingAllowance = slice.members.length * 0.00005 + 0.0001
  if (!Number.isFinite(converted) || converted < 0 || converted > 100 + roundingAllowance) {
    throw new TypeError("Snapshot allocation is not chart-compatible.")
  }
  return converted > 100 ? 100 : converted
}

function buildSegments(
  slices: readonly SnapshotAllocationExactSlice[]
): SnapshotAllocationSegment[] {
  let offset = 0
  return slices.map((slice, index) => {
    const value = toChartNumber(slice)
    const segment = {
      ...slice,
      color: COLORS[index % COLORS.length] as string,
      offset,
      value,
    }
    offset += value
    return segment
  })
}

function sectorPoint(percentage: number): readonly [number, number] {
  const angle = (percentage / 100) * Math.PI * 2 - Math.PI / 2
  return [120 + 100 * Math.cos(angle), 120 + 100 * Math.sin(angle)]
}

function sectorPath(segment: SnapshotAllocationSegment): string {
  if (segment.value <= 0) return ""
  if (segment.value >= 100) {
    return "M 120 20 A 100 100 0 1 1 120 220 A 100 100 0 1 1 120 20 Z"
  }
  const start = sectorPoint(segment.offset)
  const end = sectorPoint(Math.min(100, segment.offset + segment.value))
  const largeArc = segment.value > 50 ? 1 : 0
  return `M 120 120 L ${start[0]} ${start[1]} A 100 100 0 ${largeArc} 1 ${end[0]} ${end[1]} Z`
}

function tooltipText(slice: SnapshotAllocationExactSlice): string {
  const summary = `${slice.name}: ${formatSnapshotPercentage(slice.exactAllocation)} %`
  if (slice.name !== "Ostatní") return summary
  return `${summary}\n${slice.members
    .map((member) => `${member.name}: ${formatSnapshotPercentage(member.allocationPct)} %`)
    .join("\n")}`
}

export function SnapshotAllocationPie({ items }: { items: readonly SnapshotAllocationItem[] }) {
  const data = buildSegments(buildSnapshotAllocationSlices(items))
  if (data.length === 0 || !data.some((slice) => slice.value > 0)) {
    return (
      <div className="flex h-[344px] items-center justify-center text-center text-sm text-gray-500">
        Pro tento stav není alokace dostupná.
      </div>
    )
  }

  return (
    <div className="flex h-[344px] flex-col items-center justify-between">
      <svg
        className="min-h-0 w-full flex-1"
        viewBox="0 0 240 240"
        role="img"
        aria-label="Koláčový graf alokace portfolia"
      >
        <circle cx="120" cy="120" r="100" fill="#e5e7eb" />
        {data
          .filter((slice) => slice.value > 0)
          .map((slice) => (
            <path
              key={slice.key}
              d={sectorPath(slice)}
              fill={slice.color}
              stroke="white"
              strokeWidth="2"
            >
              <title>{tooltipText(slice)}</title>
            </path>
          ))}
      </svg>

      <ul className="grid w-full grid-cols-2 gap-x-3 gap-y-1 text-xs text-gray-700">
        {data.map((slice) => (
          <li
            key={slice.key}
            className="flex min-w-0 items-center gap-2"
            title={tooltipText(slice)}
          >
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ backgroundColor: slice.color }}
              aria-hidden="true"
            />
            <span className="truncate">{slice.name}</span>
            <span className="ml-auto shrink-0 font-mono">
              {formatSnapshotPercentage(slice.exactAllocation)} %
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
