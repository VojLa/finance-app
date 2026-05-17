import Link from "next/link"
import type { HoldingWithPrice } from "@/types"

function fmtCzk(n: number | null | undefined) {
  if (n === null || n === undefined) return <span className="text-gray-300">—</span>
  return (
    <span>
      {n.toLocaleString("cs-CZ", { minimumFractionDigits: 0, maximumFractionDigits: 0 })} Kč
    </span>
  )
}

function fmtNum(n: number | null | undefined, decimals = 2) {
  if (n === null || n === undefined) return <span className="text-gray-300">—</span>
  return <span>{n.toLocaleString("cs-CZ", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}</span>
}

function pnlColor(n: number | null) {
  if (n === null) return "text-gray-400"
  return n >= 0 ? "text-green-600" : "text-red-600"
}

interface Props {
  holdings: HoldingWithPrice[]
  showAccount?: boolean
}

export function HoldingsTable({ holdings, showAccount }: Props) {
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
            {showAccount && <th className="pb-3 font-medium">Účet</th>}
            <th className="pb-3 font-medium text-right">Množství</th>
            <th className="pb-3 font-medium text-right">Prům. nák. cena</th>
            <th className="pb-3 font-medium text-right">Aktuální cena</th>
            <th className="pb-3 font-medium text-right">Hodnota</th>
            <th className="pb-3 font-medium text-right">Hodnota (CZK)</th>
            <th className="pb-3 font-medium text-right">P&L (CZK)</th>
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
              {showAccount && (
                <td className="py-3 text-xs text-gray-400">{h.accountName ?? "—"}</td>
              )}
              <td className="py-3 text-right font-mono">{fmtNum(h.quantity, 6)}</td>
              <td className="py-3 text-right font-mono text-gray-500">
                {fmtNum(h.avgBuyPrice)} {h.currency}
              </td>
              <td className="py-3 text-right font-mono">
                {h.currentPrice !== null
                  ? <span>{fmtNum(h.currentPrice)} {h.currentPriceCurrency}</span>
                  : <span className="text-gray-300">—</span>}
              </td>
              <td className="py-3 text-right font-mono text-gray-500">
                {h.currentValue !== null
                  ? <span>{fmtNum(h.currentValue)} {h.currentPriceCurrency}</span>
                  : <span className="text-gray-300">—</span>}
              </td>
              <td className="py-3 text-right font-mono font-medium">
                {fmtCzk(h.currentValueCzk)}
              </td>
              <td className={`py-3 text-right font-mono font-medium ${pnlColor(h.unrealizedPnlCzk)}`}>
                {h.unrealizedPnlCzk !== null
                  ? <span>{h.unrealizedPnlCzk >= 0 ? "+" : ""}{fmtCzk(h.unrealizedPnlCzk)}</span>
                  : <span className="text-gray-300">—</span>}
              </td>
              <td className={`py-3 text-right font-mono ${pnlColor(h.unrealizedPnlPct)}`}>
                {h.unrealizedPnlPct !== null
                  ? `${h.unrealizedPnlPct >= 0 ? "+" : ""}${h.unrealizedPnlPct.toLocaleString("cs-CZ", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
