"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import Link from "next/link"
import type { HoldingWithPrice } from "@/types"

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

function fmt(n: number | null | undefined, decimals = 2) {
  if (n === null || n === undefined) return "—"
  return n.toLocaleString("cs-CZ", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

const TYPE_LABELS: Record<string, string> = {
  buy: "Nákup", sell: "Prodej", dividend: "Dividenda",
  interest: "Úrok", deposit: "Vklad", withdrawal: "Výběr",
  currency_conversion: "Konverze", staking_reward: "Staking", airdrop: "Airdrop", fee: "Poplatek",
}

export default function SymbolPage() {
  const { symbol } = useParams<{ symbol: string }>()
  const [holding, setHolding] = useState<HoldingWithPrice | null>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetch("/api/portfolio").then(r => r.json()),
      fetch(`/api/portfolio/transactions?symbol=${symbol}`).then(r => r.json()),
    ]).then(([portfolio, txs]) => {
      setHolding(portfolio.holdings?.find((h: HoldingWithPrice) => h.symbol === symbol) ?? null)
      setTransactions(txs)
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

  const pnlPos = (holding.unrealizedPnl ?? 0) >= 0

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/portfolio" className="text-gray-400 hover:text-gray-600 text-sm">← Portfolio</Link>
        <h1 className="text-2xl font-semibold">{symbol}</h1>
        {holding.name && <span className="text-gray-500">{holding.name}</span>}
      </div>

      {/* Statistiky */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Množství</p>
          <p className="text-xl font-semibold font-mono">{fmt(holding.quantity, 6)}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Prům. nák. cena</p>
          <p className="text-xl font-semibold font-mono">{fmt(holding.avgBuyPrice)} {holding.currency}</p>
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
          <p className="text-sm text-gray-500 mb-1">Nerealizovaný P&L</p>
          <p className={`text-xl font-semibold font-mono ${pnlPos ? "text-green-600" : "text-red-600"}`}>
            {holding.unrealizedPnl !== null
              ? `${pnlPos ? "+" : ""}${fmt(holding.unrealizedPnl)} ${holding.currentPriceCurrency ?? ""}`
              : "—"}
          </p>
          {holding.unrealizedPnlPct !== null && (
            <p className={`text-sm ${pnlPos ? "text-green-600" : "text-red-600"}`}>
              {pnlPos ? "+" : ""}{fmt(holding.unrealizedPnlPct)}%
            </p>
          )}
        </div>
      </div>

      {/* Transakce */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-lg font-medium mb-4">Historie transakcí</h2>
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
                  <th className="pb-3 font-medium text-right">Cena</th>
                  <th className="pb-3 font-medium text-right">Celkem</th>
                  <th className="pb-3 font-medium text-right">P&L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {transactions.map(tx => (
                  <tr key={tx.id}>
                    <td className="py-2.5 text-gray-500">
                      {new Date(tx.date).toLocaleDateString("cs-CZ")}
                    </td>
                    <td className="py-2.5">{TYPE_LABELS[tx.type] ?? tx.type}</td>
                    <td className="py-2.5 text-right font-mono">{fmt(tx.quantity, 6)}</td>
                    <td className="py-2.5 text-right font-mono">
                      {tx.pricePerUnit !== null ? `${fmt(tx.pricePerUnit)} ${tx.priceCurrency ?? ""}` : "—"}
                    </td>
                    <td className="py-2.5 text-right font-mono">
                      {tx.totalAmount !== null ? `${fmt(tx.totalAmount)} ${tx.totalCurrency ?? ""}` : "—"}
                    </td>
                    <td className={`py-2.5 text-right font-mono ${tx.realizedPnl !== null && tx.realizedPnl >= 0 ? "text-green-600" : "text-red-600"}`}>
                      {tx.realizedPnl !== null ? `${tx.realizedPnl >= 0 ? "+" : ""}${fmt(tx.realizedPnl)} ${tx.realizedPnlCurrency ?? ""}` : "—"}
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
