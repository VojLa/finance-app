"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { HoldingsTable } from "@/components/portfolio/HoldingsTable"
import { AllocationPie } from "@/components/charts/AllocationPie"
import {
  PortfolioLineChart,
  type PortfolioChartDataPoint,
  type PortfolioChartRange,
  type PortfolioValueMode,
} from "@/components/charts/PortfolioLineChart"
import type { PortfolioSummary } from "@/types"
import { fmtCzk, fmtPct } from "@/lib/format"

function fmtCurrencyAmount(amount: number, _currency: string) {
  return amount.toLocaleString("cs-CZ", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function cashAmountCzk(
  amount: number,
  currency: string,
  rates: Record<string, number> | undefined
) {
  if (currency === "CZK") return amount
  const rate = rates?.[currency]
  return rate ? amount * rate : null
}

export default function PortfolioPage() {
  const [data, setData] = useState<PortfolioSummary | null>(null)
  const [netWorthHistory, setNetWorthHistory] = useState<PortfolioChartDataPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [recalculatingSnapshots, setRecalculatingSnapshots] = useState(false)
  const [snapshotMessage, setSnapshotMessage] = useState<string | null>(null)
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null)
  const [historyRange, setHistoryRange] = useState<PortfolioChartRange>("1Y")
  const [portfolioValueMode, setPortfolioValueMode] = useState<PortfolioValueMode>("total")
  const [activeHistoryPoint, setActiveHistoryPoint] = useState<PortfolioChartDataPoint | null>(null)
  const [historyLocked, setHistoryLocked] = useState(false)

  const load = useCallback(
    async (refresh = false) => {
      const accountParam = selectedAccountId ? `accountId=${selectedAccountId}&` : ""
      const portfolioUrl =
        `/api/portfolio?${accountParam}${refresh ? `_t=${Date.now()}` : ""}`.replace(/\?$/, "")
      const historyParams = new URLSearchParams({ range: historyRange })
      if (selectedAccountId) historyParams.set("accountId", selectedAccountId)
      const historyUrl = `/api/portfolio/history?${historyParams.toString()}`

      if (refresh) {
        setRefreshing(true)
        await fetch("/api/rates?refresh=true")
      }

      const [portfolio, netWorth] = await Promise.all([
        fetch(portfolioUrl).then((r) => r.json()),
        fetch(historyUrl).then((r) => r.json()),
      ])
      setData(portfolio)
      setNetWorthHistory(Array.isArray(netWorth) ? netWorth : [])
      setLoading(false)
      setRefreshing(false)
    },
    [historyRange, selectedAccountId]
  )

  const recalculateSnapshots = useCallback(async () => {
    setRecalculatingSnapshots(true)
    setSnapshotMessage(null)

    try {
      const res = await fetch("/api/portfolio/snapshots/recalculate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(selectedAccountId ? { accountId: selectedAccountId } : {}),
      })
      const result = await res.json()

      if (!res.ok) {
        throw new Error(result?.error || "Prepocteni snapshotu selhalo")
      }

      setSnapshotMessage(`Prepocteno ${result.snapshots ?? 0} dennich snapshotu.`)
      await load(true)
    } catch (error) {
      setSnapshotMessage(error instanceof Error ? error.message : "Prepocteni snapshotu selhalo")
    } finally {
      setRecalculatingSnapshots(false)
    }
  }, [load, selectedAccountId])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    setActiveHistoryPoint(null)
    setHistoryLocked(false)
  }, [historyRange, selectedAccountId])

  if (loading) {
    return <div className="text-gray-400 py-12 text-center">Načítám portfolio...</div>
  }

  const accounts = data?.accounts ?? []
  const warnings = data?.warnings ?? []
  const latestHistoryPoint = netWorthHistory.at(-1) ?? null
  const displayPoint = activeHistoryPoint ?? latestHistoryPoint
  const pointNetWorthCzk = displayPoint?.netWorthCzk ?? displayPoint?.valueCzk ?? null
  const pointCashCzk = displayPoint?.cashCzk ?? 0
  const pointInvestmentValueCzk =
    pointNetWorthCzk !== null ? Math.max(0, pointNetWorthCzk - pointCashCzk) : null
  const displayTotalValueCzk =
    portfolioValueMode === "total"
      ? (pointNetWorthCzk ?? data?.totalValueCzk ?? 0)
      : (pointInvestmentValueCzk ?? data?.totalValueCzk ?? 0)
  const displayBaselineCzk =
    portfolioValueMode === "total"
      ? (displayPoint?.netDepositsCzk ?? data?.totalCostCzk ?? 0)
      : (displayPoint?.investedCzk ?? data?.totalCostCzk ?? 0)
  const displayPnlCzk = displayTotalValueCzk - displayBaselineCzk
  const displayReturnPct = displayBaselineCzk > 0 ? (displayPnlCzk / displayBaselineCzk) * 100 : 0
  const displayCashCzk = displayPoint?.cashCzk ?? 0
  const displayRealizedPnlCzk = displayPoint?.realizedPnlCzk ?? data?.totalRealizedPnlCzk ?? 0
  const displayUnrealizedPnlCzk = displayPoint?.unrealizedPnlCzk ?? data?.totalUnrealizedPnlCzk ?? 0
  const pnlPositive = displayPnlCzk >= 0
  const realizedPnlPositive = displayRealizedPnlCzk >= 0
  const unrealizedPnlPositive = displayUnrealizedPnlCzk >= 0
  const displayedHoldings = displayPoint?.positions ?? data?.holdings ?? []
  const displayCashByCurrency =
    displayPoint?.cashByCurrency && Object.keys(displayPoint.cashByCurrency).length > 0
      ? displayPoint.cashByCurrency
      : displayCashCzk !== 0
        ? { CZK: displayCashCzk }
        : {}
  const cashBreakdown = Object.entries(displayCashByCurrency)
    .filter(([, amount]) => Math.abs(amount) >= 0.005)
    .map(([currency, amount]) => ({
      currency,
      amount,
      amountCzk: cashAmountCzk(amount, currency, data?.czkRates),
    }))
    .sort((a, b) => Math.abs(b.amountCzk ?? b.amount) - Math.abs(a.amountCzk ?? a.amount))
  const hasAllocationData =
    displayedHoldings.length > 0 || (portfolioValueMode === "total" && displayCashCzk > 0)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Portfolio</h1>
        <div className="flex gap-2">
          <Link
            href="/portfolio/add"
            className="flex items-center gap-1.5 text-sm text-white bg-blue-600 hover:bg-blue-700 rounded-lg px-3 py-1.5 transition-colors"
          >
            + Přidat transakci
          </Link>
          <button
            onClick={() => load(true)}
            disabled={refreshing}
            className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-800 border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50 disabled:opacity-50 transition-colors"
          >
            <span className={refreshing ? "animate-spin inline-block" : ""}>↻</span>
            {refreshing ? "Aktualizuji..." : "Aktualizovat ceny"}
          </button>
          <button
            onClick={recalculateSnapshots}
            disabled={recalculatingSnapshots}
            className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-800 border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50 disabled:opacity-50 transition-colors"
          >
            <span className={recalculatingSnapshots ? "animate-spin inline-block" : ""}>â†»</span>
            {recalculatingSnapshots ? "Prepocitavam..." : "Prepocitat snapshoty"}
          </button>
        </div>
      </div>

      {snapshotMessage && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-2 text-sm text-gray-600">
          {snapshotMessage}
        </div>
      )}

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
          {accounts.map((a) => (
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
              <p key={i} className="text-sm text-amber-700">
                {w.symbol}: {w.issue}
              </p>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">
            {portfolioValueMode === "total" ? "Celkova hodnota" : "Hodnota investic"}
          </p>
          <p className="text-2xl font-semibold">{fmtCzk(displayTotalValueCzk)}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">
            {portfolioValueMode === "total" ? "Vlozeno" : "Investovano"}
          </p>
          <p className="text-2xl font-semibold">{fmtCzk(displayBaselineCzk)}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Realizovane P&L</p>
          <p
            className={`text-2xl font-semibold ${realizedPnlPositive ? "text-green-600" : "text-red-600"}`}
          >
            {realizedPnlPositive ? "+" : ""}
            {fmtCzk(displayRealizedPnlCzk)}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Nerealizovane P&L</p>
          <p
            className={`text-2xl font-semibold ${unrealizedPnlPositive ? "text-green-600" : "text-red-600"}`}
          >
            {unrealizedPnlPositive ? "+" : ""}
            {fmtCzk(displayUnrealizedPnlCzk)}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Hotovost</p>
          <p className="text-2xl font-semibold">{fmtCzk(displayCashCzk)}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm text-gray-500 mb-1">Vynos</p>
          <p
            className={`text-2xl font-semibold ${pnlPositive ? "text-green-600" : "text-red-600"}`}
          >
            {fmtPct(displayReturnPct)}
          </p>
        </div>
      </div>

      {data?.czkRates && (
        <div className="flex gap-4 text-xs text-gray-400">
          <span>
            1 EUR ={" "}
            {data.czkRates["EUR"]?.toLocaleString("cs-CZ", {
              minimumFractionDigits: 3,
              maximumFractionDigits: 3,
            })}{" "}
            Kč
          </span>
          <span>
            1 USD ={" "}
            {data.czkRates["USD"]?.toLocaleString("cs-CZ", {
              minimumFractionDigits: 3,
              maximumFractionDigits: 3,
            })}{" "}
            Kč
          </span>
        </div>
      )}

      {netWorthHistory.length > 1 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <PortfolioLineChart
            data={netWorthHistory}
            currentValueCzk={displayTotalValueCzk}
            range={historyRange}
            onRangeChange={setHistoryRange}
            valueMode={portfolioValueMode}
            onValueModeChange={setPortfolioValueMode}
            activePoint={displayPoint}
            isLocked={historyLocked}
            onActivePointChange={setActiveHistoryPoint}
            onActivePointReset={() => setActiveHistoryPoint(null)}
            onLockedChange={setHistoryLocked}
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-medium mb-4">Pozice</h2>
          <HoldingsTable
            holdings={displayedHoldings}
            showAccount={selectedAccountId === null && accounts.length > 1}
          />
        </div>
        <div className="space-y-6">
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-lg font-medium">Hotovost podle men</h2>
              <span className="text-sm font-medium text-gray-500">{fmtCzk(displayCashCzk)}</span>
            </div>
            {cashBreakdown.length > 0 ? (
              <div className="space-y-3">
                {cashBreakdown.map((cash) => (
                  <div
                    key={cash.currency}
                    className="flex items-center justify-between gap-3 border-b border-gray-100 pb-3 last:border-b-0 last:pb-0"
                  >
                    <div>
                      <p className="text-sm font-medium text-gray-900">{cash.currency}</p>
                      {cash.amountCzk !== null && cash.currency !== "CZK" && (
                        <p className="text-xs text-gray-400">{fmtCzk(cash.amountCzk)}</p>
                      )}
                    </div>
                    <p className="text-sm font-semibold tabular-nums text-gray-900">
                      {fmtCurrencyAmount(cash.amount, cash.currency)} {cash.currency}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="py-6 text-center text-sm text-gray-400">Zadna hotovost</p>
            )}
          </div>

          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-lg font-medium mb-4">Alokace (CZK)</h2>
            {hasAllocationData ? (
              <AllocationPie
                holdings={displayedHoldings}
                cashCzk={displayCashCzk}
                includeCash={portfolioValueMode === "total"}
              />
            ) : (
              <div className="text-center text-gray-400 py-8 text-sm">
                <p className="mb-3">Žádné pozice</p>
                <Link href="/portfolio/add" className="text-blue-500 hover:underline">
                  Přidat první transakci →
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
