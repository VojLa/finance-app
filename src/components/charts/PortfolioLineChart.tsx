"use client"

import { useMemo } from "react"
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import type { TooltipProps } from "recharts"
import type { HoldingWithPrice } from "@/types"

export interface PortfolioChartDataPoint {
  timestamp?: string
  month: string
  label: string
  investedCzk: number
  netDepositsCzk?: number
  cashCzk?: number
  investmentCostBasisCzk?: number
  realizedPnlCzk?: number
  unrealizedPnlCzk?: number
  valueCzk?: number
  netWorthCzk?: number
  allocations?: { symbol: string; accountId: string; valueCzk: number; allocationPct: number }[]
  positions?: HoldingWithPrice[]
}

export type PortfolioChartRange = "1W" | "1M" | "3M" | "6M" | "1Y" | "ALL"
export type PortfolioValueMode = "investments" | "total"

type ChartPoint = PortfolioChartDataPoint & {
  baselineCzk: number
  displayValueCzk: number
  dateLabel: string
}

type ChartMouseState = {
  activePayload?: Array<{ payload?: ChartPoint }>
}

interface Props {
  data: PortfolioChartDataPoint[]
  currentValueCzk?: number
  range: PortfolioChartRange
  onRangeChange: (range: PortfolioChartRange) => void
  valueMode: PortfolioValueMode
  onValueModeChange: (mode: PortfolioValueMode) => void
  activePoint?: PortfolioChartDataPoint | null
  isLocked?: boolean
  onActivePointChange?: (point: PortfolioChartDataPoint) => void
  onLockedChange?: (locked: boolean) => void
}

const RANGES: { label: string; value: PortfolioChartRange }[] = [
  { label: "Tyden", value: "1W" },
  { label: "Mesic", value: "1M" },
  { label: "3 mes.", value: "3M" },
  { label: "6 mes.", value: "6M" },
  { label: "1 rok", value: "1Y" },
  { label: "Vse", value: "ALL" },
]

function fmtCzk(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} M Kc`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)} tis. Kc`
  return `${n} Kc`
}

function pointDateLabel(point: PortfolioChartDataPoint) {
  if (!point.timestamp) return point.label
  const date = new Date(point.timestamp)
  if (Number.isNaN(date.getTime())) return point.label
  return date.toLocaleDateString("cs-CZ", {
    day: "numeric",
    month: "short",
    year: "numeric",
  })
}

function getChartPoint(state: ChartMouseState | null | undefined) {
  return state?.activePayload?.[0]?.payload ?? null
}

function isChartPoint(value: unknown): value is ChartPoint {
  return typeof value === "object" && value !== null && "dateLabel" in value
}

export function PortfolioLineChart({
  data,
  currentValueCzk,
  range,
  onRangeChange,
  valueMode,
  onValueModeChange,
  activePoint,
  isLocked = false,
  onActivePointChange,
  onLockedChange,
}: Props) {
  const hasNetWorth = data.some((d) => d.netWorthCzk !== undefined)
  const showValueMode = hasNetWorth && data.some((d) => d.cashCzk !== undefined)

  const chartData = useMemo(
    () =>
      data.map((d, i) => {
        const netWorthCzk = d.netWorthCzk ?? d.investedCzk
        const investmentValueCzk =
          d.cashCzk !== undefined ? Math.max(0, netWorthCzk - d.cashCzk) : netWorthCzk
        const baselineCzk =
          valueMode === "total" ? (d.netDepositsCzk ?? d.investedCzk) : d.investedCzk

        return {
          ...d,
          baselineCzk,
          dateLabel: pointDateLabel(d),
          displayValueCzk: valueMode === "total" ? netWorthCzk : investmentValueCzk,
          currentCzk:
            i === data.length - 1 && currentValueCzk && valueMode === "investments"
              ? currentValueCzk
              : undefined,
        }
      }),
    [currentValueCzk, data, valueMode]
  )

  if (data.length === 0) return null

  const title =
    hasNetWorth && valueMode === "investments"
      ? "Historicky vyvoj investic"
      : hasNetWorth
        ? "Historicky vyvoj ciste hodnoty"
        : "Vyvoj investovane castky"
  const valueLabel = valueMode === "total" ? "Investice + cash" : "Jen investice"
  const baselineLabel = valueMode === "total" ? "Vlozeno" : "Investovano"
  const activeDateLabel = activePoint ? pointDateLabel(activePoint) : null

  const handleMouseMove = (state: ChartMouseState) => {
    if (isLocked) return
    const point = getChartPoint(state)
    if (point) onActivePointChange?.(point)
  }

  const handleClick = (state: ChartMouseState) => {
    const point = getChartPoint(state)

    if (isLocked) {
      onLockedChange?.(false)
      if (point) onActivePointChange?.(point)
      return
    }

    if (point) {
      onActivePointChange?.(point)
      onLockedChange?.(true)
    }
  }

  const renderDateTooltip = ({ active, payload }: TooltipProps<number, string>) => {
    if (!active || isLocked) return null
    const point = payload?.[0]?.payload
    if (!isChartPoint(point)) return null

    return (
      <div className="rounded-md border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-gray-700 shadow-sm">
        {point.dateLabel}
      </div>
    )
  }

  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-medium">{title}</h2>
          {activeDateLabel && (
            <span className="rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-500">
              {isLocked ? "Zamceno" : "Vybrano"}: {activeDateLabel}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {showValueMode && (
            <button
              type="button"
              role="switch"
              aria-checked={valueMode === "total"}
              onClick={() => onValueModeChange(valueMode === "total" ? "investments" : "total")}
              className="flex h-8 items-center gap-2 rounded-lg border border-gray-200 bg-white px-2 text-xs font-medium text-gray-600 transition-colors hover:border-gray-300 hover:text-gray-900"
            >
              <span
                className={`relative h-4 w-7 rounded-full transition-colors ${
                  valueMode === "total" ? "bg-gray-900" : "bg-gray-300"
                }`}
              >
                <span
                  className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-transform ${
                    valueMode === "total" ? "translate-x-3.5" : "translate-x-0.5"
                  }`}
                />
              </span>
              {valueLabel}
            </button>
          )}
          <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
            {RANGES.map((r) => (
              <button
                key={r.value}
                onClick={() => onRangeChange(r.value)}
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
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart
          data={chartData}
          margin={{ top: 4, right: 8, left: 0, bottom: 0 }}
          onMouseMove={handleMouseMove}
          onClick={handleClick}
        >
          <defs>
            <linearGradient id="investedGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.15} />
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="netWorthGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#10b981" stopOpacity={0.15} />
              <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
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
            content={renderDateTooltip}
            cursor={{ stroke: "#94a3b8", strokeDasharray: "4 4" }}
          />
          {hasNetWorth && <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />}
          <Area
            type="linear"
            dataKey="baselineCzk"
            name={baselineLabel}
            stroke="#3b82f6"
            strokeWidth={2}
            strokeLinecap="butt"
            strokeLinejoin="miter"
            fill="url(#investedGrad)"
            dot={false}
            activeDot={{ r: 4 }}
          />
          {hasNetWorth && (
            <Area
              type="linear"
              dataKey="displayValueCzk"
              name={valueLabel}
              stroke="#10b981"
              strokeWidth={2}
              strokeLinecap="butt"
              strokeLinejoin="miter"
              fill="url(#netWorthGrad)"
              dot={false}
              activeDot={{ r: 4 }}
            />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
