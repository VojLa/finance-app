"use client"

import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts"

import type { PortfolioPagePosition } from "./snapshot-page-model"

const COLORS = [
  "#3b82f6",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#ec4899",
  "#06b6d4",
  "#84cc16",
]

type Props = {
  positions: readonly PortfolioPagePosition[]
  showAccount: boolean
}

type AllocationSlice = {
  name: string
  value: number
  exactAllocation: string
}

/**
 * Presentation-only conversion at the Recharts leaf boundary.
 * The returned number is never written back to view state or used for finance.
 */
function toChartNumber(value: string): number {
  const converted = Number(value)
  if (!Number.isFinite(converted)) {
    throw new TypeError("Snapshot allocation is not chart-compatible.")
  }
  return converted
}

export function SnapshotAllocationPie({ positions, showAccount }: Props) {
  const data: AllocationSlice[] = positions.map(({ accountName, position }) => ({
    name: showAccount ? `${position.symbol} · ${accountName}` : position.symbol,
    value: toChartNumber(position.allocationPct),
    exactAllocation: position.allocationPct,
  }))

  if (data.length === 0) return null

  return (
    <ResponsiveContainer width="100%" height={280}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={70}
          outerRadius={110}
          paddingAngle={2}
          dataKey="value"
        >
          {data.map((slice, index) => (
            <Cell key={`${slice.name}:${index}`} fill={COLORS[index % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          formatter={(_value, _name, item) => [
            `${(item.payload as AllocationSlice).exactAllocation} %`,
            "Alokace",
          ]}
        />
        <Legend />
      </PieChart>
    </ResponsiveContainer>
  )
}
