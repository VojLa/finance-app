"use client"

import { useEffect, useState } from "react"
import { HoldingsTable } from "@/components/portfolio/HoldingsTable"
import { AllocationPie } from "@/components/charts/AllocationPie"
import type { PortfolioSummary } from "@/types"

function fmt(n: number) {
  return n.toLocaleString("cs-CZ", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export default function PortfolioPage() {
  const [data, setData] = useState<PortfolioSummary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch("/api/portfolio")
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
  }, [])

  if (loading) {
    return <div className="text-gray-400 py-12 text-center">Načítám portfolio...</div>
  }

  const pnlPositive = (data?.totalUnrealizedPnl ?? 0) >= 0

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Portfolio</h1>

      {/* Souhrn */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Celková hodnota</p>
          <p className="text-2xl font-semibold">{fmt(data?.totalValue ?? 0)}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Investováno</p>
          <p className="text-2xl font-semibold">{fmt(data?.totalCost ?? 0)}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Nerealizovaný P&L</p>
          <p className={`text-2xl font-semibold ${pnlPositive ? "text-green-600" : "text-red-600"}`}>
            {pnlPositive ? "+" : ""}{fmt(data?.totalUnrealizedPnl ?? 0)}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Výnos</p>
          <p className={`text-2xl font-semibold ${pnlPositive ? "text-green-600" : "text-red-600"}`}>
            {pnlPositive ? "+" : ""}{fmt(data?.totalUnrealizedPnlPct ?? 0)}%
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Tabulka pozic */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-medium mb-4">Pozice</h2>
          <HoldingsTable holdings={data?.holdings ?? []} />
        </div>

        {/* Alokace */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-medium mb-4">Alokace</h2>
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
