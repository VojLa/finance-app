"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import Link from "next/link"
import type { HoldingWithPrice } from "@/types"
import { fmt, fmtCzk, fmtPct } from "@/lib/format"

type Transaction = {
  id: string
  date: string
  type: string
  quantity: number | null
  pricePerUnit: number | null
  priceCurrency: string | null
  totalAmount: number | null
  totalCurrency: string | null
  fee: number | null
  feeCurrency: string | null
  realizedPnl: number | null
  realizedPnlCurrency: string | null
}

const TYPE_LABELS: Record<string, string> = {
  buy: "Nákup", sell: "Prodej", dividend: "Dividenda",
  interest: "Úrok", deposit: "Vklad", withdrawal: "Výběr",
  currency_conversion: "Konverze", staking_reward: "Staking", airdrop: "Airdrop", fee: "Poplatek",
}

const TYPE_BADGE_COLORS: Record<string, string> = {
  buy: "bg-blue-50 text-blue-700",
  sell: "bg-orange-50 text-orange-700",
  dividend: "bg-green-50 text-green-700",
}

export default function SymbolPage() {
  const { symbol } = useParams<{ symbol: string }>()
  const [holding, setHolding] = useState<HoldingWithPrice | null>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetch("/api/portfolio").then(r => r.json()),
      fetch(`/api/portfolio/transactions?symbol=${encodeURIComponent(symbol)}`).then(r => r.json()),
    ]).then(([portfolio, txs]) => {
      setHolding(portfolio.holdings?.find((h: HoldingWithPrice) => h.symbol === symbol) ?? null)
      setTransactions(Array.isArray(txs) ? txs : [])
      setLoading(false)
    })
  }, [symbol])

  if (loading) return <div className="text-gray-400 py-12 text-center">Načítám...</div>
  if (!holding) return (
    <div className="text-center py-12">
      <p className="text-gray-500 mb-4">Symbol {symbol} nenalezen v portfoliu.</p>
      <Link href="/portfolio" className="text-blue-600 hover:underline">← Portfolio</Link>
    </div>
  )

  const pnlPos = (holding.unrealizedPnlCzk ?? 0) >= 0

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/portfolio" className="text-gray-400 hover:text-gray-600 text-sm">← Portfolio</Link>
        <h1 className="text-2xl font-semibold">{symbol}</h1>
        {holding.name && <span className="text-gray-500 text-lg">{holding.name}</span>}
        <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full uppercase">
          {holding.assetType}
        </span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Množství</p>
          <p className="text-xl font-semibold font-mono">{fmt(holding.quantity, 6)}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Prům. nák. cena</p>
          <p className="text-xl font-semibold font-mono">{fmt(holding.avgBuyPrice)} {holding.currency}</p>
          <p className="text-xs text-gray-400 mt-0.5">{fmtCzk(holding.avgBuyPriceCzk)}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Aktuální cena</p>
          <p className="text-xl font-semibold font-mono">
            {holding.currentPrice !== null
              ? `${fmt(holding.currentPrice)} ${holding.currentPriceCurrency ?? ""}`
              : "—"}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Hodnota</p>
          <p className="text-xl font-semibold font-mono">
            {holding.currentValue !== null
              ? `${fmt(holding.currentValue)} ${holding.currentPriceCurrency ?? ""}`
              : "—"}
          </p>
          <p className="text-xs text-gray-400 mt-0.5">{fmtCzk(holding.currentValueCzk)}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Nerealizovaný P&L</p>
          <p className={`text-xl font-semibold font-mono ${pnlPos ? "text-green-600" : "text-red-600"}`}>
            {holding.unrealizedPnlCzk !== null
              ? `${pnlPos ? "+" : ""}${fmtCzk(holding.unrealizedPnlCzk)}`
              : "—"}
          </p>
          {holding.unrealizedPnlPct !== null && (
            <p className={`text-sm font-mono ${pnlPos ? "text-green-600" : "text-red-600"}`}>
              {fmtPct(holding.unrealizedPnlPct)}
            </p>
          )}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-lg font-medium mb-4">Historie transakcí ({transactions.length})</h2>
        {transactions.length === 0 ? (
          <p className="text-gray-400 text-sm">Žádné transakce.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-gray-500 text-left">
                  <th className="pb-3 font-medium">Datum</th>
                  <th className="pb-3 font-medium">Typ</th>
                  <th className="pb-3 font-medium text-right">Množství</th>
                  <th className="pb-3 font-medium text-right">Cena / ks</th>
                  <th className="pb-3 font-medium text-right">Celkem</th>
                  <th className="pb-3 font-medium text-right">Poplatek</th>
                  <th className="pb-3 font-medium text-right">Realizovaný P&L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {transactions.map(tx => (
                  <tr key={tx.id} className="hover:bg-gray-50">
                    <td className="py-2.5 text-gray-500">
                      {new Date(tx.date).toLocaleDateString("cs-CZ")}
                    </td>
                    <td className="py-2.5">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${TYPE_BADGE_COLORS[tx.type] ?? "bg-gray-50 text-gray-600"}`}>
                        {TYPE_LABELS[tx.type] ?? tx.type}
                      </span>
                    </td>
                    <td className="py-2.5 text-right font-mono">{fmt(tx.quantity, 6)}</td>
                    <td className="py-2.5 text-right font-mono text-gray-500">
                      {tx.pricePerUnit !== null ? `${fmt(tx.pricePerUnit)} ${tx.priceCurrency ?? ""}` : "—"}
                    </td>
                    <td className="py-2.5 text-right font-mono font-medium">
                      {tx.totalAmount !== null ? `${fmt(tx.totalAmount)} ${tx.totalCurrency ?? ""}` : "—"}
                    </td>
                    <td className="py-2.5 text-right font-mono text-gray-400">
                      {tx.fee !== null ? `${fmt(tx.fee)} ${tx.feeCurrency ?? ""}` : "—"}
                    </td>
                    <td className={`py-2.5 text-right font-mono ${tx.realizedPnl !== null && tx.realizedPnl >= 0 ? "text-green-600" : tx.realizedPnl !== null ? "text-red-600" : "text-gray-300"}`}>
                      {tx.realizedPnl !== null
                        ? `${tx.realizedPnl >= 0 ? "+" : ""}${fmt(tx.realizedPnl)} ${tx.realizedPnlCurrency ?? ""}`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
