import { formatSnapshotAmount } from "@/modules/portfolio/snapshot-page-format"

import type { SnapshotDashboardModel } from "./snapshot-dashboard-model"

type Props = {
  model: SnapshotDashboardModel
}

export function SnapshotSummaryCards({ model }: Props) {
  const cards = [
    ["Celková hodnota", model.summary.totalValue],
    ["Aktiva", model.summary.assetsValue],
    ["Závazky", model.summary.liabilitiesValue],
    ["Hotovost", model.summary.cashValue],
    ["Investice", model.summary.investmentValue],
    ["Nákladová báze", model.summary.investmentCostBasis],
    ["Realizované P/L", model.summary.realizedPnlValue],
    ["Nerealizované P/L", model.summary.unrealizedPnlValue],
  ] as const

  return (
    <section aria-labelledby="snapshot-summary-heading" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="snapshot-summary-heading" className="text-lg font-medium">
            Snapshot finanční přehled
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            {model.summary.accountCount} účtů · {model.summary.positionCount} pozic
          </p>
        </div>
        <p className="text-sm text-gray-500">Výstupní měna: {model.currency}</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-gray-200 bg-white p-5">
            <p className="text-sm text-gray-500">{label}</p>
            <p className="mt-2 text-xl font-semibold tabular-nums">
              {formatSnapshotAmount(value, model.currency)}
            </p>
          </div>
        ))}
      </div>
    </section>
  )
}
