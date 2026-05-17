"use client"

import { useCallback, useEffect, useState } from "react"
import { HoldingsTable } from "@/components/portfolio/HoldingsTable"
import { AllocationPie } from "@/components/charts/AllocationPie"
import { PortfolioLineChart } from "@/components/charts/PortfolioLineChart"
import type { PortfolioSummary } from "@/types"
import { fmtCzk, fmtPct } from "@/lib/format"

interface HistoryPoint {
  month: string
  label: string
  investedCzk: number
}

export default function PortfolioPage() {
  const [data, setData] = useState<PortfolioSummary | null>(null)
  const [history, setHistory] = useState<HistoryPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null)

  const load = useCallback(async (refresh = false) => {
    const accountParam = selectedAccountId ? `accountId=${selectedAccountId}&` : ""
    const portfolioUrl = `/api/portfolio?${accountParam}${refresh ? `_t=${Date.now()}` : ""}`.replace(/\?$/, "")
    const historyUrl = `/api/portfolio/history${selectedAccountId ? `?accountId=${selectedAccountId}` : ""}`

    if (refresh) {
      setRefreshing(true)
      await fetch("/api/rates?refresh=true")
    }

    const [portfolio, hist] = await Promise.all([
      fetch(portfolioUrl).then(r => r.json()),
      fetch(historyUrl).then(r => r.json()),
    ])
    setData(portfolio)
    setHistory(Array.isArray(hist) ? hist : [])
    setLoading(false)
    setRefreshing(false)
  }, [selectedAccountId])

  useEffect(() => { load() }, [load])

  if (loading) {
    return <div className="text-gray-400 py-12 text-center">Načítám portfolio...</div>
  }

  const pnlPositive = (data?.totalUnrealizedPnlCzk ?? 0) >= 0
  const accounts = data?.accounts ?? []
  const warnings = data?.warnings ?? []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Portfolio</h1>
        <button
          onClick={() => load(true)}
          disabled={refreshing}
          className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-800 border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          <span className={refreshing ? "animate-spin inline-block" : ""}>↻</span>
          {refreshing ? "Aktualizuji..." : "Aktualizovat ceny"}
        </button>
      </div>

      {accounts.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => setSelectedAccountId(null)}
            className={`px-4 py-1.5 text-sm rounded-full border transition-colors ${
              selectedAccountId === null
                ? "bg-gray-900 text-white border-gray-900"
                : "border-gray-200 text-gray-600 hover:border-gray-400"
            }`}
          >
            Vše
          </button>
          {accounts.map(a => (
            <button
              key={a.id}
              onClick={() => setSelectedAccountId(a.id)}
              className={`px-4 py-1.5 text-sm rounded-full border transition-colors ${
                selectedAccountId === a.id
                  ? "bg-gray-900 text-white border-gray-900"
                  : "border-gray-200 text-gray-600 hover:border-gray-400"
              }`}
            >
              {a.name}
            </button>
          ))}
        </div>
      )}

      {warnings.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-start gap-3">
          <span className="text-amber-500 mt-0.5">&#9888;</span>
          <div>
            <p className="font-medium text-amber-800 text-sm">Upozornění na data portfolia</p>
            {warnings.map((w, i) => (
              <p key={i} className="text-sm text-amber-700">{w.symbol}: {w.issue}</p>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Celková hodnota</p>
          <p className="text-2xl font-semibold">{fmtCzk(data?.totalValueCzk ?? 0)}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Investováno</p>
          <p className="text-2xl font-semibold">{fmtCzk(data?.totalCostCzk ?? 0)}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Nerealizovaný P&L</p>
          <p className={`text-2xl font-semibold ${pnlPositive ? "text-green-600" : "text-red-600"}`}>
            {pnlPositive ? "+" : ""}{fmtCzk(data?.totalUnrealizedPnlCzk ?? 0)}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Výnos</p>
          <p className={`text-2xl font-semibold ${pnlPositive ? "text-green-600" : "text-red-600"}`}>
            {fmtPct(data?.totalUnrealizedPnlPct ?? 0)}
          </p>
        </div>
      </div>

      {data?.czkRates && (
        <div className="flex gap-4 text-xs text-gray-400">
          <span>1 EUR = {data.czkRates["EUR"]?.toLocaleString("cs-CZ", { minimumFractionDigits: 3, maximumFractionDigits: 3 })} Kč</span>
          <span>1 USD = {data.czkRates["USD"]?.toLocaleString("cs-CZ", { minimumFractionDigits: 3, maximumFractionDigits: 3 })} Kč</span>
        </div>
      )}

      {history.length > 1 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <PortfolioLineChart data={history} currentValueCzk={data?.totalValueCzk} />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-medium mb-4">Pozice</h2>
          <HoldingsTable
            holdings={data?.holdings ?? []}
            showAccount={selectedAccountId === null && accounts.length > 1}
          />
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-medium mb-4">Alokace (CZK)</h2>
          {(data?.holdings.length ?? 0) > 0 ? (
            <AllocationPie holdings={data!.holdings} />
          ) : (
            <div className="text-center text-gray-400 py-8">Žádná data</div>
          )}
        </div>
      </div>
    </div>
  )
}
