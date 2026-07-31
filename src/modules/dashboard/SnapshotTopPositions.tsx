import {
  formatSnapshotAmount,
  formatSnapshotDecimal,
} from "@/modules/portfolio/snapshot-page-format"

import type { SnapshotDashboardModel } from "./snapshot-dashboard-model"

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

export function SnapshotTopPositions({ model }: Props) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-lg font-medium">Největší pozice</h2>
        <span className="text-xs text-gray-400">Pořadí ze snapshot backendu</span>
      </div>
      {model.topPositions.length === 0 ? (
        <p className="py-12 text-center text-sm text-gray-400">Žádné investiční pozice.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-gray-500">
                <th className="pb-3 font-medium">Pozice</th>
                <th className="pb-3 font-medium">Účet</th>
                <th className="pb-3 text-right font-medium">Hodnota</th>
                <th className="pb-3 text-right font-medium">Nerealizované P/L</th>
                <th className="pb-3 text-right font-medium">Alokace</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {model.topPositions.map((position) => (
                <tr key={`${position.accountId}:${position.listingId}`}>
                  <td className="py-3">
                    <p className="font-medium">{position.symbol}</p>
                    <p className="text-xs text-gray-400">
                      {position.name} ·{" "}
                      {ASSET_TYPE_LABELS[position.assetType] ?? position.assetType}
                    </p>
                  </td>
                  <td className="py-3 text-xs text-gray-500">{position.accountId}</td>
                  <td className="py-3 text-right font-mono font-medium">
                    {formatSnapshotAmount(position.value, position.valueCurrency)}
                  </td>
                  <td className="py-3 text-right font-mono">
                    {formatSnapshotAmount(position.unrealizedPnl, position.valueCurrency)}
                  </td>
                  <td className="py-3 text-right font-mono">
                    {formatSnapshotDecimal(position.allocationPct)} %
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
