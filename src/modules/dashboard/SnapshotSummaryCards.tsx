import Link from "next/link"

import { formatSnapshotAmount } from "@/modules/portfolio/snapshot-page-format"

import type { SnapshotDashboardModel } from "./snapshot-dashboard-model"

type Props = {
  model: SnapshotDashboardModel
}

export function SnapshotSummaryCards({ model }: Props) {
  const details = [
    ["Investice", model.summary.investmentValue],
    ["Hotovost", model.summary.cashValue],
    ["Závazky", model.summary.liabilitiesValue],
  ] as const

  return (
    <section
      aria-labelledby="snapshot-summary-heading"
      className="overflow-hidden rounded-2xl bg-slate-950 text-white shadow-sm"
    >
      <div className="p-6 sm:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-slate-300">Celkový zůstatek</p>
            <h2
              id="snapshot-summary-heading"
              className="mt-2 text-3xl font-semibold tracking-tight tabular-nums sm:text-4xl"
            >
              {formatSnapshotAmount(model.summary.totalValue, model.currency)}
            </h2>
          </div>
          <span className="rounded-full bg-white/10 px-3 py-1.5 text-xs font-medium text-slate-200">
            {model.summary.accountCount} účtů
          </span>
        </div>
        <dl className="mt-7 grid gap-4 sm:grid-cols-3">
          {details.map(([label, value]) => (
            <div key={label} className="rounded-xl bg-white/8 px-4 py-3">
              <dt className="text-xs text-slate-300">{label}</dt>
              <dd className="mt-1 font-medium tabular-nums">
                {formatSnapshotAmount(value, model.currency)}
              </dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="flex justify-end border-t border-white/10 px-6 py-4 sm:px-7">
        <Link href="/portfolio" className="text-sm font-medium text-sky-300 hover:text-sky-200">
          Zobrazit více
        </Link>
      </div>
    </section>
  )
}
