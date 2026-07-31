"use client"

import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts"

import { formatSnapshotAmount } from "@/modules/portfolio/snapshot-page-format"

import type { SnapshotDashboardModel } from "./snapshot-dashboard-model"

const COLORS = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#db2777"]

const ASSET_TYPE_LABELS: Record<string, string> = {
  stock: "Akcie",
  etf: "ETF",
  crypto: "Kryptoměny",
  commodity: "Komodity",
  cash: "Hotovost",
  bond: "Dluhopisy",
  other: "Ostatní",
}

type Props = {
  model: SnapshotDashboardModel
}

type AllocationSlice = SnapshotDashboardModel["assetTypeAllocations"][number] & {
  name: string
  chartValue: number
}

/**
 * Presentation-only Decimal conversion required by Recharts.
 * The number is never reused for finance or written back to snapshot state.
 */
function toChartNumber(value: string): number {
  const converted = Number(value)
  if (!Number.isFinite(converted)) {
    throw new TypeError("Snapshot allocation is not chart-compatible.")
  }
  return converted
}

export function SnapshotAssetAllocationChart({ model }: Props) {
  const data: AllocationSlice[] = model.assetTypeAllocations.map((allocation) => ({
    ...allocation,
    name: ASSET_TYPE_LABELS[allocation.assetType] ?? allocation.assetType,
    chartValue: toChartNumber(allocation.allocationPct),
  }))

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-5">
      <div className="mb-4">
        <h2 className="text-lg font-medium">Alokace podle typu aktiv</h2>
        <p className="mt-1 text-xs text-gray-400">Vypočteno snapshot backendem</p>
      </div>
      {data.length === 0 ? (
        <p className="py-12 text-center text-sm text-gray-400">Žádná investiční alokace.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-[1fr_0.9fr]">
          <ResponsiveContainer width="100%" height={280}>
            <PieChart>
              <Pie
                data={data}
                dataKey="chartValue"
                nameKey="name"
                innerRadius={68}
                outerRadius={105}
                paddingAngle={2}
              >
                {data.map((item, index) => (
                  <Cell key={item.assetType} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                formatter={(_value, _name, item) => [
                  `${(item.payload as AllocationSlice).allocationPct} %`,
                  "Alokace",
                ]}
              />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
          <div className="space-y-3 self-center">
            {data.map((item, index) => (
              <div key={item.assetType} className="flex items-center justify-between gap-3 text-sm">
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: COLORS[index % COLORS.length] }}
                  />
                  <span className="truncate">{item.name}</span>
                </span>
                <span className="text-right">
                  <span className="block font-medium tabular-nums">{item.allocationPct} %</span>
                  <span className="block text-xs text-gray-400">
                    {formatSnapshotAmount(item.value, model.currency)} · {item.positionCount} pozic
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
