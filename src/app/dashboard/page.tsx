"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import type { PortfolioSummary } from "@/types"

function fmt(n: number) {
  return n.toLocaleString("cs-CZ", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export default function DashboardPage() {
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch("/api/portfolio")
      .then(r => r.json())
      .then(d => { setPortfolio(d); setLoading(false) })
  }, [])

  const pnlPos = (portfolio?.totalUnrealizedPnl ?? 0) >= 0
  const top3 = portfolio?.holdings.slice(0, 3) ?? []

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      {/* Portfolio souhrn */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Hodnota portfolia</p>
          {loading ? (
            <div className="h-8 bg-gray-100 rounded animate-pulse w-24" />
          ) : (
            <p className="text-2xl font-semibold">{fmt(portfolio?.totalValue ?? 0)}</p>
          )}
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Investováno</p>
          {loading ? (
            <div className="h-8 bg-gray-100 rounded animate-pulse w-24" />
          ) : (
            <p className="text-2xl font-semibold">{fmt(portfolio?.totalCost ?? 0)}</p>
          )}
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Celkový P&L</p>
          {loading ? (
            <div className="h-8 bg-gray-100 rounded animate-pulse w-24" />
          ) : (
            <div>
              <p className={`text-2xl font-semibold ${pnlPos ? "text-green-600" : "text-red-600"}`}>
                {pnlPos ? "+" : ""}{fmt(portfolio?.totalUnrealizedPnl ?? 0)}
              </p>
              <p className={`text-sm ${pnlPos ? "text-green-600" : "text-red-600"}`}>
                {pnlPos ? "+" : ""}{fmt(portfolio?.totalUnrealizedPnlPct ?? 0)}%
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Top pozice */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium">Největší pozice</h2>
          <Link href="/portfolio" className="text-sm text-blue-600 hover:underline">
            Celé portfolio →
          </Link>
        </div>
        {loading ? (
          <div className="space-y-3">
            {[0, 1, 2].map(i => (
              <div key={i} className="h-10 bg-gray-100 rounded animate-pulse" />
            ))}
          </div>
        ) : top3.length === 0 ? (
          <div className="text-center py-8 text-gray-400">
            <p className="mb-3">Portfolio je prázdné.</p>
            <Link href="/import" className="text-blue-600 hover:underline text-sm">
              Importovat CSV →
            </Link>
          </div>
        ) : (
          <div className="space-y-3">
            {top3.map(h => (
              <Link
                key={h.id}
                href={`/portfolio/${h.symbol}`}
                className="flex items-center justify-between p-3 rounded-lg hover:bg-gray-50 transition-colors"
              >
                <div>
                  <span className="font-medium">{h.symbol}</span>
                  {h.name && <span className="text-sm text-gray-500 ml-2">{h.name}</span>}
                </div>
                <div className="text-right">
                  <p className="font-medium font-mono">
                    {h.currentValue !== null ? `${fmt(h.currentValue)} ${h.currentPriceCurrency ?? ""}` : "—"}
                  </p>
                  {h.unrealizedPnlPct !== null && (
                    <p className={`text-sm font-mono ${(h.unrealizedPnlPct ?? 0) >= 0 ? "text-green-600" : "text-red-600"}`}>
                      {(h.unrealizedPnlPct ?? 0) >= 0 ? "+" : ""}{fmt(h.unrealizedPnlPct)}%
                    </p>
                  )}
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* Quick links */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { href: "/portfolio", label: "Portfolio", desc: "Přehled pozic" },
          { href: "/import", label: "Import CSV", desc: "Trading 212, Anycoin" },
          { href: "/accounts", label: "Účty", desc: "Správa účtů" },
          { href: "/transactions", label: "Transakce", desc: "Historie (brzy)" },
        ].map(item => (
          <Link
            key={item.href}
            href={item.href}
            className="bg-white rounded-xl border border-gray-200 p-4 hover:border-blue-300 hover:shadow-sm transition-all"
          >
            <p className="font-medium text-sm">{item.label}</p>
            <p className="text-xs text-gray-400 mt-0.5">{item.desc}</p>
          </Link>
        ))}
      </div>
    </div>
  )
}
