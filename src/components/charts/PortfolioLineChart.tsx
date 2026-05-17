"use client"

import { useMemo, useState } from "react"
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts"

interface DataPoint {
  month: string
  label: string
  investedCzk: number
}

interface Props {
  data: DataPoint[]
  currentValueCzk?: number
}

type Range = "3M" | "6M" | "1Y" | "ALL"

const RANGES: { label: string; value: Range; months: number | null }[] = [
  { label: "3 měs.", value: "3M", months: 3 },
  { label: "6 měs.", value: "6M", months: 6 },
  { label: "1 rok", value: "1Y", months: 12 },
  { label: "Vše", value: "ALL", months: null },
]

function fmtCzk(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} M Kč`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)} tis. Kč`
  return `${n} Kč`
}

export function PortfolioLineChart({ data, currentValueCzk }: Props) {
  const [range, setRange] = useState<Range>("ALL")

  const filtered = useMemo(() => {
    if (range === "ALL") return data
    const cutoff = new Date()
    const months = RANGES.find(r => r.value === range)!.months!
    cutoff.setMonth(cutoff.getMonth() - months)
    const cutoffStr = cutoff.toISOString().slice(0, 7)
    return data.filter(d => d.month >= cutoffStr)
  }, [data, range])

  if (data.length === 0) return null

  const chartData = filtered.map((d, i) => ({
    ...d,
    currentCzk: i === filtered.length - 1 && currentValueCzk ? currentValueCzk : undefined,
  }))

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-medium">Vývoj investované částky</h2>
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
          {RANGES.map(r => (
            <button
              key={r.value}
              onClick={() => setRange(r.value)}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                range === r.value
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="investedGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.15} />
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tickFormatter={fmtCzk}
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            tickLine={false}
            axisLine={false}
            width={72}
            domain={["auto", "auto"]}
          />
          <Tooltip
            formatter={(value: number) => [
              value.toLocaleString("cs-CZ", { minimumFractionDigits: 0, maximumFractionDigits: 0 }) + " Kč",
            ]}
            labelStyle={{ color: "#1e293b", fontWeight: 500 }}
            contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 13 }}
          />
          <Area
            type="monotone"
            dataKey="investedCzk"
            name="Investováno"
            stroke="#3b82f6"
            strokeWidth={2}
            fill="url(#investedGrad)"
            dot={false}
            activeDot={{ r: 4 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
