import Link from "next/link"

import type { PortfolioPagePosition } from "./snapshot-page-model"
import { formatSnapshotAmount, formatSnapshotDecimal } from "./snapshot-page-format"

type Props = {
  positions: readonly PortfolioPagePosition[]
  showAccount: boolean
}

export function SnapshotHoldingsTable({ positions, showAccount }: Props) {
  if (positions.length === 0) {
    return <div className="py-12 text-center text-gray-400">Žádné snapshot-backed pozice.</div>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 text-left text-gray-500">
            <th className="pb-3 font-medium">Symbol</th>
            {showAccount && <th className="pb-3 font-medium">Účet</th>}
            <th className="pb-3 text-right font-medium">Množství</th>
            <th className="pb-3 text-right font-medium">Cena</th>
            <th className="pb-3 text-right font-medium">Hodnota</th>
            <th className="pb-3 text-right font-medium">Nákladová báze</th>
            <th className="pb-3 text-right font-medium">Nerealizované P/L</th>
            <th className="pb-3 text-right font-medium">Alokace</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {positions.map(({ accountId, accountName, position }) => (
            <tr
              key={`${accountId}:${position.listingId}`}
              className="transition-colors hover:bg-gray-50"
            >
              <td className="py-3">
                <Link
                  href={`/portfolio/${encodeURIComponent(position.symbol)}`}
                  className="font-medium text-blue-600 hover:underline"
                >
                  {position.symbol}
                </Link>
                <p className="text-xs text-gray-400">{position.name}</p>
              </td>
              {showAccount && <td className="py-3 text-xs text-gray-500">{accountName}</td>}
              <td className="py-3 text-right font-mono">
                {formatSnapshotDecimal(position.quantity)}
              </td>
              <td className="py-3 text-right font-mono text-gray-600">
                {formatSnapshotAmount(position.pricePerUnit, position.priceCurrency)}
              </td>
              <td className="py-3 text-right font-mono font-medium">
                {formatSnapshotAmount(position.value, position.valueCurrency)}
              </td>
              <td className="py-3 text-right font-mono text-gray-600">
                {formatSnapshotAmount(position.costBasis, position.costCurrency)}
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
  )
}
