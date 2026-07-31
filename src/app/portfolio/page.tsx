"use client"

import Link from "next/link"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import {
  PortfolioLineChart,
  type PortfolioChartDataPoint,
  type PortfolioChartRange,
  type PortfolioValueMode,
} from "@/components/charts/PortfolioLineChart"
import { SnapshotAllocationPie } from "@/modules/portfolio/SnapshotAllocationPie"
import { SnapshotHoldingsTable } from "@/modules/portfolio/SnapshotHoldingsTable"
import { requestPortfolioHistory } from "@/modules/portfolio/snapshot-history-client"
import {
  requestPortfolioPageState,
  type PortfolioPageState,
} from "@/modules/portfolio/snapshot-page-client"
import {
  formatSnapshotAmount,
  formatSnapshotTimestamp,
} from "@/modules/portfolio/snapshot-page-format"
import {
  buildPortfolioPageModel,
  selectPortfolioAccountView,
} from "@/modules/portfolio/snapshot-page-model"

export default function PortfolioPage() {
  const [state, setState] = useState<PortfolioPageState>({ status: "loading" })
  const [refreshing, setRefreshing] = useState(false)
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null)
  const [history, setHistory] = useState<PortfolioChartDataPoint[]>([])
  const [historyRange, setHistoryRange] = useState<PortfolioChartRange>("1Y")
  const [historyValueMode, setHistoryValueMode] = useState<PortfolioValueMode>("total")
  const initialLoadStarted = useRef(false)

  const loadPortfolio = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    try {
      // Current values have one authority: POST /api/snapshot-workflow/portfolio.
      setState(await requestPortfolioPageState())
    } finally {
      if (isRefresh) setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    if (initialLoadStarted.current) return
    initialLoadStarted.current = true
    void loadPortfolio()
  }, [loadPortfolio])

  useEffect(() => {
    let active = true
    void requestPortfolioHistory(historyRange).then((points) => {
      if (active) setHistory(points)
    })
    return () => {
      active = false
    }
  }, [historyRange])

  const pageModel = useMemo(
    () => (state.status === "ready" ? buildPortfolioPageModel(state.data) : null),
    [state]
  )
  const selectedAccount = useMemo(() => {
    if (!pageModel || selectedAccountId === null) return null
    return selectPortfolioAccountView(pageModel, selectedAccountId)
  }, [pageModel, selectedAccountId])

  useEffect(() => {
    if (selectedAccountId !== null && pageModel && selectedAccount === null) {
      setSelectedAccountId(null)
    }
  }, [pageModel, selectedAccount, selectedAccountId])

  const refreshDisabled = state.status === "loading" || refreshing

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <h1 className="text-2xl font-semibold">Portfolio</h1>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/portfolio/add"
            className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white transition-colors hover:bg-blue-700"
          >
            + Přidat transakci
          </Link>
          <button
            type="button"
            onClick={() => void loadPortfolio(true)}
            disabled={refreshDisabled}
            className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 transition-colors hover:bg-gray-50 hover:text-gray-900 disabled:opacity-50"
          >
            <span className={refreshing ? "inline-block animate-spin" : ""}>↻</span>
            {refreshing ? "Aktualizuji portfolio…" : "Aktualizovat portfolio"}
          </button>
        </div>
      </div>

      {state.status === "loading" && (
        <div
          role="status"
          className="rounded-xl border border-gray-200 bg-white py-12 text-center text-gray-500"
        >
          Načítám snapshot-backed portfolio…
        </div>
      )}

      {state.status === "error" && (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-5">
          <p className="font-medium text-red-800">Portfolio se nepodařilo načíst</p>
          <p className="mt-1 text-sm text-red-700">{state.message}</p>
        </div>
      )}

      {state.status === "empty" && (
        <>
          <RefreshMetadata refresh={state.refresh} />
          <div className="rounded-xl border border-gray-200 bg-white p-8 text-center">
            <h2 className="text-lg font-medium text-gray-900">Zatím nemáte žádný účet</h2>
            <p className="mx-auto mt-2 max-w-lg text-sm text-gray-500">
              Snapshot workflow proběhl úspěšně, ale nemá žádný účet, ze kterého by mohl sestavit
              portfolio.
            </p>
            <Link
              href="/accounts"
              className="mt-5 inline-flex rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              Přidat nebo spravovat účet
            </Link>
          </div>
        </>
      )}

      {state.status === "ready" && pageModel && (
        <ReadyPortfolio
          state={state}
          model={pageModel}
          selectedAccountId={selectedAccountId}
          selectedAccount={selectedAccount}
          onSelectAccount={setSelectedAccountId}
          history={history}
          historyRange={historyRange}
          onHistoryRangeChange={setHistoryRange}
          historyValueMode={historyValueMode}
          onHistoryValueModeChange={setHistoryValueMode}
        />
      )}
    </div>
  )
}

type RefreshMetadataProps = {
  refresh: Extract<PortfolioPageState, { status: "empty" | "ready" }>["refresh"]
}

function RefreshMetadata({ refresh }: RefreshMetadataProps) {
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-1 rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
      <span>Aktualizováno: {formatSnapshotTimestamp(refresh.timestamp)}</span>
      <span>Měna: {refresh.currency}</span>
      <span>Stav: {refresh.netWorthStatus === "created" ? "vytvořeno" : "zopakováno"}</span>
    </div>
  )
}

type ReadyPortfolioProps = {
  state: Extract<PortfolioPageState, { status: "ready" }>
  model: ReturnType<typeof buildPortfolioPageModel>
  selectedAccountId: string | null
  selectedAccount: ReturnType<typeof selectPortfolioAccountView>
  onSelectAccount: (accountId: string | null) => void
  history: PortfolioChartDataPoint[]
  historyRange: PortfolioChartRange
  onHistoryRangeChange: (range: PortfolioChartRange) => void
  historyValueMode: PortfolioValueMode
  onHistoryValueModeChange: (mode: PortfolioValueMode) => void
}

function ReadyPortfolio({
  state,
  model,
  selectedAccountId,
  selectedAccount,
  onSelectAccount,
  history,
  historyRange,
  onHistoryRangeChange,
  historyValueMode,
  onHistoryValueModeChange,
}: ReadyPortfolioProps) {
  const view = selectedAccount ?? model.aggregate
  const showAccount = view.scope === "aggregate" && model.accounts.length > 1
  const summaryCards = [
    ["Celková hodnota", view.summary.totalValue],
    ["Hodnota investic", view.summary.investmentValue],
    ["Nákladová báze investic", view.summary.investmentCostBasis],
    ["Hotovost", view.summary.cashValue],
    ["Realizované P/L", view.summary.realizedPnlValue],
    ["Nerealizované P/L", view.summary.unrealizedPnlValue],
  ] as const

  return (
    <>
      <RefreshMetadata refresh={state.refresh} />

      {model.accounts.length > 1 && (
        <div className="flex flex-wrap gap-2" aria-label="Výběr účtu">
          <button
            type="button"
            onClick={() => onSelectAccount(null)}
            aria-pressed={selectedAccountId === null}
            className={`rounded-full border px-4 py-1.5 text-sm transition-colors ${
              selectedAccountId === null
                ? "border-gray-900 bg-gray-900 text-white"
                : "border-gray-200 text-gray-600 hover:border-gray-400"
            }`}
          >
            Vše
          </button>
          {model.accounts.map((account) => (
            <button
              type="button"
              key={account.accountId}
              onClick={() => onSelectAccount(account.accountId)}
              aria-pressed={selectedAccountId === account.accountId}
              className={`rounded-full border px-4 py-1.5 text-sm transition-colors ${
                selectedAccountId === account.accountId
                  ? "border-gray-900 bg-gray-900 text-white"
                  : "border-gray-200 text-gray-600 hover:border-gray-400"
              }`}
            >
              {account.label} · {account.accountCurrency}
            </button>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        {summaryCards.map(([label, value]) => (
          <div key={label} className="rounded-xl border border-gray-200 bg-white p-5">
            <p className="mb-1 text-sm text-gray-500">{label}</p>
            <p className="text-xl font-semibold">{formatSnapshotAmount(value, view.currency)}</p>
          </div>
        ))}
      </div>

      {history.length > 1 && (
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          {/* 5M-C keeps legacy history chart-only; it never overrides current snapshot values. */}
          <PortfolioLineChart
            data={history}
            range={historyRange}
            onRangeChange={onHistoryRangeChange}
            valueMode={historyValueMode}
            onValueModeChange={onHistoryValueModeChange}
          />
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="rounded-xl border border-gray-200 bg-white p-6 lg:col-span-2">
          <h2 className="mb-4 text-lg font-medium">Pozice</h2>
          <SnapshotHoldingsTable positions={view.positions} showAccount={showAccount} />
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="mb-4 text-lg font-medium">Alokace</h2>
          {view.hasServerAllocation ? (
            <SnapshotAllocationPie positions={view.positions} showAccount={showAccount} />
          ) : (
            <p className="py-8 text-center text-sm text-gray-500">
              Souhrnná alokace přes více účtů zatím není v portfolio snapshot response dostupná.
            </p>
          )}
        </div>
      </div>
    </>
  )
}
