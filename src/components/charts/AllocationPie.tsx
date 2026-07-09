"use client"

import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from "recharts"
import type { HoldingWithPrice } from "@/types"

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

interface Props {
  holdings: HoldingWithPrice[]
  cashCzk?: number
  includeCash?: boolean
}

export function AllocationPie({ holdings, cashCzk = 0, includeCash = false }: Props) {
  const data = [
    ...holdings
      .filter((h) => h.currentValueCzk && h.currentValueCzk > 0)
      .map((h) => ({ name: h.symbol, value: Math.round(h.currentValueCzk!) })),
    ...(includeCash && cashCzk > 0 ? [{ name: "Cash", value: Math.round(cashCzk) }] : []),
  ]

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
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip formatter={(value: number) => [`${value.toFixed(2)}`, "Hodnota"]} />
        <Legend />
      </PieChart>
    </ResponsiveContainer>
  )
}
