"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import type { PortfolioSummary, CashSummary } from "@/types"
import { fmtCzk, fmtPct, fmt } from "@/lib/format"

export default function DashboardPage() {
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null)
  const [cash, setCash] = useState<CashSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [cashLoading, setCashLoading] = useState(true)

  useEffect(() => {
    fetch("/api/portfolio")
      .then(r => r.json())
      .then(d => { setPortfolio(d); setLoading(false) })

    fetch("/api/accounts/cash")
      .then(r => r.json())
      .then(d => { setCash(d); setCashLoading(false) })
  }, [])

  const pnlPos = (portfolio?.totalUnrealizedPnlCzk ?? 0) >= 0
  const top3 = portfolio?.holdings.slice(0, 3) ?? []

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Hodnota portfolia</p>
          {loading ? (
            <div className="h-8 bg-gray-100 rounded animate-pulse w-32" />
          ) : (
            <p className="text-2xl font-semibold">{fmtCzk(portfolio?.totalValueCzk ?? 0)}</p>
          )}
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Investováno</p>
          {loading ? (
            <div className="h-8 bg-gray-100 rounded animate-pulse w-32" />
          ) : (
            <p className="text-2xl font-semibold">{fmtCzk(portfolio?.totalCostCzk ?? 0)}</p>
          )}
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Celkový P&L</p>
          {loading ? (
            <div className="h-8 bg-gray-100 rounded animate-pulse w-32" />
          ) : (
            <div>
              <p className={`text-2xl font-semibold ${pnlPos ? "text-green-600" : "text-red-600"}`}>
                {pnlPos ? "+" : ""}{fmtCzk(portfolio?.totalUnrealizedPnlCzk ?? 0)}
              </p>
              <p className={`text-sm ${pnlPos ? "text-green-600" : "text-red-600"}`}>
                {fmtPct(portfolio?.totalUnrealizedPnlPct ?? 0)}
              </p>
            </div>
          )}
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Volná hotovost</p>
          {cashLoading ? (
            <div className="h-8 bg-gray-100 rounded animate-pulse w-32" />
          ) : (
            <p className="text-2xl font-semibold">{fmtCzk(cash?.totalCashCzk ?? 0)}</p>
          )}
        </div>
      </div>

      {portfolio?.czkRates && (
        <div className="flex gap-4 text-sm text-gray-400">
          <span>1 EUR = {portfolio.czkRates["EUR"]?.toLocaleString("cs-CZ", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} Kč</span>
          <span>1 USD = {portfolio.czkRates["USD"]?.toLocaleString("cs-CZ", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} Kč</span>
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-lg font-medium mb-4">Volné zůstatky po účtech</h2>
        {cashLoading ? (
          <div className="space-y-3">
            {[0, 1, 2].map(i => (
              <div key={i} className="h-12 bg-gray-100 rounded animate-pulse" />
            ))}
          </div>
        ) : !cash || cash.accounts.length === 0 ? (
          <div className="text-center py-8 text-gray-400">
            <p className="mb-3">Žádné transakce nenalezeny.</p>
            <Link href="/import" className="text-blue-600 hover:underline text-sm">
              Importovat CSV →
            </Link>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {cash.accounts.map(account => (
              <div key={account.accountId} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-2">
                    {account.color && (
                      <span
                        className="inline-block w-2.5 h-2.5 rounded-full"
                        style={{ backgroundColor: account.color }}
                      />
                    )}
                    <span className="font-medium text-sm">{account.accountName}</span>
                    <span className="text-xs text-gray-400 capitalize">{account.accountType}</span>
                  </div>
                  <span className="font-semibold text-sm">{fmtCzk(account.totalCzk)}</span>
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-0.5 pl-4">
                  {account.balances.map(b => (
                    <span key={b.currency} className="text-xs text-gray-500">
                      {fmt(b.amount, b.currency === "CZK" ? 0 : 2)} {b.currency}
                      {b.currency !== "CZK" && (
                        <span className="text-gray-400 ml-1">({fmtCzk(b.amountCzk)})</span>
                      )}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

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
            {top3.map(h => {
              const pos = (h.unrealizedPnlPct ?? 0) >= 0
              return (
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
                    <p className="font-medium">{fmtCzk(h.currentValueCzk ?? 0)}</p>
                    {h.unrealizedPnlPct !== null && (
                      <p className={`text-sm ${pos ? "text-green-600" : "text-red-600"}`}>
                        {fmtPct(h.unrealizedPnlPct)}
                      </p>
                    )}
                  </div>
                </Link>
              )
            })}
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { href: "/portfolio", label: "Portfolio", desc: "Přehled pozic" },
          { href: "/import", label: "Import CSV", desc: "Trading 212, Anycoin" },
          { href: "/accounts", label: "Účty", desc: "Správa účtů" },
          { href: "/budget", label: "Rozpočty", desc: "Měsíční přehledy" },
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
