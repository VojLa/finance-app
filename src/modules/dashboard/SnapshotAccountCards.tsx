import Link from "next/link"

import { ACCOUNT_TYPE_LABELS } from "@/lib/constants"
import { formatSnapshotAmount } from "@/modules/portfolio/snapshot-page-format"

import type { SnapshotDashboardModel } from "./snapshot-dashboard-model"

type Props = {
  model: SnapshotDashboardModel
}

export function SnapshotAccountCards({ model }: Props) {
  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-lg font-medium">Finanční účty</h2>
        <span className="text-xs text-gray-400">{model.summary.positionCount} pozic</span>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {model.accounts.slice(0, 3).map((account) => (
          <article
            key={account.accountId}
            className="rounded-xl border border-gray-100 bg-slate-50 p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate font-medium text-gray-900">{account.name}</h3>
                <p className="text-xs text-gray-500">
                  {ACCOUNT_TYPE_LABELS[account.accountType] ?? account.accountType} ·{" "}
                  {account.accountCurrency}
                </p>
              </div>
              <span className="text-xs text-gray-400">{account.positionCount} pozic</span>
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
              <div>
                <dt className="text-xs text-gray-400">Celkem</dt>
                <dd className="font-medium">
                  {formatSnapshotAmount(account.totalValue, account.accountCurrency)}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-gray-400">Investice</dt>
                <dd>{formatSnapshotAmount(account.investmentValue, account.accountCurrency)}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-400">Hotovost</dt>
                <dd>{formatSnapshotAmount(account.cashValue, account.accountCurrency)}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-400">Závazky</dt>
                <dd>{formatSnapshotAmount(account.liabilitiesValue, account.accountCurrency)}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-xs text-gray-400">Čisté vklady</dt>
                <dd>{formatSnapshotAmount(account.netDepositsValue, account.accountCurrency)}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-xs text-gray-400">Nerealizované P/L</dt>
                <dd>{formatSnapshotAmount(account.unrealizedPnlValue, account.accountCurrency)}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
      <div className="mt-5 flex justify-end border-t border-gray-100 pt-4">
        <Link href="/accounts" className="text-sm font-medium text-blue-600 hover:underline">
          Zobrazit více
        </Link>
      </div>
    </section>
  )
}
