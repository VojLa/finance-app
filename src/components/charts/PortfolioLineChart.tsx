"use client"

import { useMemo } from "react"
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import type { TooltipProps } from "recharts"

import type { SnapshotPortfolioHistoryRange } from "@/modules/portfolio/snapshot-history-contract"
import { formatSnapshotAmount } from "@/modules/portfolio/snapshot-page-format"
import {
  buildPortfolioHistoryChartPoints,
  type PortfolioHistoryChartPoint,
  type PortfolioHistoryChartProps,
  type PortfolioHistoryValueMode,
} from "./portfolio-history-chart"

export type { PortfolioHistoryValueMode } from "./portfolio-history-chart"

const RANGES: ReadonlyArray<{
  label: string
  value: SnapshotPortfolioHistoryRange
}> = [
  { label: "Týden", value: "1W" },
  { label: "Měsíc", value: "1M" },
  { label: "3 měs.", value: "3M" },
  { label: "6 měs.", value: "6M" },
  { label: "1 rok", value: "1Y" },
  { label: "Vše", value: "ALL" },
]

function chartTitle(valueMode: PortfolioHistoryValueMode): string {
  return valueMode === "netWorth" ? "Historický vývoj čisté hodnoty" : "Historický vývoj investic"
}

function valueModeLabel(valueMode: PortfolioHistoryValueMode): string {
  return valueMode === "netWorth" ? "Čistá hodnota" : "Investice"
}

function formatAxisValue(value: number, currency: string): string {
  const formatted = new Intl.NumberFormat("cs-CZ", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value)
  return `${formatted} ${currency}`
}

function isChartPoint(value: unknown): value is PortfolioHistoryChartPoint {
  return typeof value === "object" && value !== null && "exactValue" in value
}

export function PortfolioLineChart({
  points,
  currency,
  range,
  onRangeChange,
  valueMode,
  onValueModeChange,
}: PortfolioHistoryChartProps) {
  const chartData = useMemo(
    () => buildPortfolioHistoryChartPoints(points, valueMode),
    [points, valueMode]
  )

  const renderTooltip = ({ active, payload }: TooltipProps<number, string>) => {
    if (!active) return null
    const point = payload?.[0]?.payload
    if (!isChartPoint(point)) return null

    return (
      <div className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm shadow-sm">
        <p className="text-gray-500">{point.dateLabel}</p>
        <p className="font-medium text-gray-900">
          {formatSnapshotAmount(point.exactValue, currency)}
        </p>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-lg font-medium">{chartTitle(valueMode)}</h3>
          <p className="text-sm text-gray-500">Měna historie: {currency}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1 rounded-lg bg-gray-100 p-1" aria-label="Hodnota grafu">
            {(["netWorth", "investments"] as const).map((mode) => (
              <button
                type="button"
                key={mode}
                aria-pressed={valueMode === mode}
                onClick={() => onValueModeChange(mode)}
                className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                  valueMode === mode
                    ? "bg-white text-gray-900 shadow-sm"
                    : "text-gray-500 hover:text-gray-700"
                }`}
              >
                {valueModeLabel(mode)}
              </button>
            ))}
          </div>
          <div
            className="flex flex-wrap gap-1 rounded-lg bg-gray-100 p-1"
            aria-label="Období grafu"
          >
            {RANGES.map((item) => (
              <button
                type="button"
                key={item.value}
                aria-pressed={range === item.value}
                onClick={() => onRangeChange(item.value)}
                className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                  range === item.value
                    ? "bg-white text-gray-900 shadow-sm"
                    : "text-gray-500 hover:text-gray-700"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {chartData.length === 0 ? (
        <p className="py-12 text-center text-sm text-gray-500">
          Pro zvolené období zatím nejsou dostupné žádné snapshoty.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="portfolioHistoryGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#10b981" stopOpacity={0.15} />
                <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis
              dataKey="dateLabel"
              tick={{ fontSize: 11, fill: "#94a3b8" }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tickFormatter={(value: number) => formatAxisValue(value, currency)}
              tick={{ fontSize: 11, fill: "#94a3b8" }}
              tickLine={false}
              axisLine={false}
              width={88}
              domain={["auto", "auto"]}
            />
            <Tooltip
              content={renderTooltip}
              cursor={{ stroke: "#94a3b8", strokeDasharray: "4 4" }}
            />
            <Area
              type="linear"
              dataKey="displayValue"
              name={valueModeLabel(valueMode)}
              stroke="#10b981"
              strokeWidth={2}
              strokeLinecap="butt"
              strokeLinejoin="miter"
              fill="url(#portfolioHistoryGradient)"
              dot={chartData.length === 1 ? { r: 4 } : false}
              activeDot={{ r: 4 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
