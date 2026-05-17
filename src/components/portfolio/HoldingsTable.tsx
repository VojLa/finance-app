import Link from "next/link"
import type { HoldingWithPrice } from "@/types"

function fmt(n: number, decimals = 2) {
  return n.toLocaleString("cs-CZ", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

function pnlColor(n: number | null) {
  if (n === null) return "text-gray-400"
  return n >= 0 ? "text-green-600" : "text-red-600"
}

interface Props {
  holdings: HoldingWithPrice[]
}

export function HoldingsTable({ holdings }: Props) {
  if (holdings.length === 0) {
    return (
      <div className="text-center py-12 text-gray-400">
        Žádné pozice. Importuj CSV z Trading 212 nebo Anycoin.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 text-gray-500 text-left">
            <th className="pb-3 font-medium">Symbol</th>
            <th className="pb-3 font-medium text-right">Množství</th>
            <th className="pb-3 font-medium text-right">Prům. nák. cena</th>
            <th className="pb-3 font-medium text-right">Aktuální cena</th>
            <th className="pb-3 font-medium text-right">Hodnota</th>
            <th className="pb-3 font-medium text-right">P&L</th>
            <th className="pb-3 font-medium text-right">P&L %</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {holdings.map(h => (
            <tr key={h.id} className="hover:bg-gray-50 transition-colors">
              <td className="py-3">
                <Link href={`/portfolio/${h.symbol}`} className="font-medium text-blue-600 hover:underline">
                  {h.symbol}
                </Link>
                {h.name && <p className="text-xs text-gray-400">{h.name}</p>}
              </td>
              <td className="py-3 text-right font-mono">{fmt(h.quantity, 6)}</td>
              <td className="py-3 text-right font-mono">
                {fmt(h.avgBuyPrice)} {h.currency}
              </td>
              <td className="py-3 text-right font-mono">
                {h.currentPrice !== null
                  ? `${fmt(h.currentPrice)} ${h.currentPriceCurrency ?? ""}`
                  : <span className="text-gray-300">—</span>}
              </td>
              <td className="py-3 text-right font-mono font-medium">
                {h.currentValue !== null
                  ? `${fmt(h.currentValue)} ${h.currentPriceCurrency ?? ""}`
                  : <span className="text-gray-300">—</span>}
              </td>
              <td className={`py-3 text-right font-mono ${pnlColor(h.unrealizedPnl)}`}>
                {h.unrealizedPnl !== null
                  ? `${h.unrealizedPnl >= 0 ? "+" : ""}${fmt(h.unrealizedPnl)} ${h.currentPriceCurrency ?? ""}`
                  : "—"}
              </td>
              <td className={`py-3 text-right font-mono ${pnlColor(h.unrealizedPnlPct)}`}>
                {h.unrealizedPnlPct !== null
                  ? `${h.unrealizedPnlPct >= 0 ? "+" : ""}${fmt(h.unrealizedPnlPct)}%`
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
