"use client"

import Link from "next/link"
import dynamic from "next/dynamic"
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react"

import { type PortfolioHistoryValueMode } from "@/components/charts/PortfolioLineChart"
import {
  EMPTY_PORTFOLIO_HISTORY_INTERACTION,
  portfolioHistoryInteractionPoint,
  reducePortfolioHistoryInteraction,
} from "@/components/charts/portfolio-history-chart"
import { SnapshotAllocationPie } from "@/modules/portfolio/SnapshotAllocationPie"
import { SnapshotCurrencyBreakdown } from "@/modules/portfolio/SnapshotCurrencyBreakdown"
import { SnapshotHoldingsTable } from "@/modules/portfolio/SnapshotHoldingsTable"
import {
  startPortfolioHistoryRequest,
  type PortfolioHistoryLoadResult,
} from "@/modules/portfolio/snapshot-history-client"
import type {
  SnapshotPortfolioHistoryPoint,
  SnapshotPortfolioHistoryRange,
} from "@/modules/portfolio/snapshot-history-contract"
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
import { resolveSnapshotPublication } from "@/lib/retain-ready-state"
import { createSerializedRefreshGate, runSerializedRefresh } from "@/lib/serialized-refresh"
import {
  isReadModelUpdateForScope,
  READ_MODEL_UPDATED_EVENT,
} from "@/modules/read-models/read-model-version-client"

const PortfolioLineChart = dynamic(
  () =>
    import("@/components/charts/PortfolioLineChart").then((module) => module.PortfolioLineChart),
  {
    ssr: false,
    loading: () => <p className="py-12 text-center text-sm text-gray-500">Načítám graf…</p>,
  }
)

export default function PortfolioPage() {
  const [state, setState] = useState<PortfolioPageState>({ status: "loading" })
  const [refreshing, setRefreshing] = useState(false)
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null)
  const [historyState, setHistoryState] = useState<
    PortfolioHistoryLoadResult | Readonly<{ status: "idle" | "loading" }>
  >({ status: "idle" })
  const [historyRange, setHistoryRange] = useState<SnapshotPortfolioHistoryRange>("1Y")
  const [historyValueMode, setHistoryValueMode] = useState<PortfolioHistoryValueMode>("netWorth")
  const [historyInteraction, dispatchHistoryInteraction] = useReducer(
    reducePortfolioHistoryInteraction,
    EMPTY_PORTFOLIO_HISTORY_INTERACTION
  )
  const selectedHistoryPoint = portfolioHistoryInteractionPoint(historyInteraction)
  const initialLoadStarted = useRef(false)
  const refreshGate = useRef(createSerializedRefreshGate())
  const lastReadyState = useRef<Extract<PortfolioPageState, { status: "ready" }> | null>(null)
  const [refreshWarning, setRefreshWarning] = useState<string | null>(null)

  const loadPortfolio = useCallback(
    (isRefresh = false) =>
      runSerializedRefresh(refreshGate.current, isRefresh, async (activeRefresh) => {
        if (activeRefresh) setRefreshing(true)
        try {
          // Python remains authoritative for both published reads and explicit refreshes.
          const next = await requestPortfolioPageState(globalThis.fetch, activeRefresh)
          const decision = resolveSnapshotPublication(next, lastReadyState.current, activeRefresh)
          lastReadyState.current = decision.lastReady
          setRefreshWarning(decision.warning)
          setState(decision.state)
        } finally {
          if (activeRefresh) setRefreshing(false)
        }
      }),
    []
  )

  useEffect(() => {
    if (initialLoadStarted.current) return
    initialLoadStarted.current = true
    void loadPortfolio()
  }, [loadPortfolio])

  useEffect(() => {
    const refreshOnReadModelUpdate = (event: Event) => {
      if (isReadModelUpdateForScope(event, "portfolio")) void loadPortfolio(true)
    }
    window.addEventListener(READ_MODEL_UPDATED_EVENT, refreshOnReadModelUpdate)
    return () => window.removeEventListener(READ_MODEL_UPDATED_EVENT, refreshOnReadModelUpdate)
  }, [loadPortfolio])

  useEffect(() => {
    const refreshOnImportCompleted = () => void loadPortfolio(true)
    window.addEventListener("finance:import-completed", refreshOnImportCompleted)
    return () => window.removeEventListener("finance:import-completed", refreshOnImportCompleted)
  }, [loadPortfolio])

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

  const historyCurrency =
    state.status === "ready" ? (selectedAccount?.currency ?? state.data.currency) : null
  const historySnapshotId = state.status === "ready" ? state.current.historyAnchorSnapshotId : null

  useEffect(() => {
    if (historyCurrency === null) {
      setHistoryState({ status: "idle" })
      return
    }

    setHistoryState({ status: "loading" })
    dispatchHistoryInteraction({ type: "reset" })
    return startPortfolioHistoryRequest(
      historyRange,
      historyCurrency,
      setHistoryState,
      globalThis.fetch,
      selectedAccountId
    )
  }, [historyCurrency, historyRange, historySnapshotId, selectedAccountId])

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

      {refreshWarning !== null && (
        <div
          role="status"
          className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
        >
          Portfolio zůstává z posledního dokončeného snapshotu. Aktualizaci se nepodařilo dokončit:{" "}
          {refreshWarning}
        </div>
      )}

      {state.status === "ready" && state.current.isStale && (
        <div
          role="status"
          className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900"
        >
          Ceny jsou starší než 30 minut. Zobrazuji poslední bezpečně publikovaný stav oceněný k{" "}
          {formatSnapshotTimestamp(state.current.valuationTimestamp)}.
        </div>
      )}

      {state.status === "ready" && pageModel && (
        <ReadyPortfolio
          state={state}
          model={pageModel}
          selectedAccountId={selectedAccountId}
          selectedAccount={selectedAccount}
          onSelectAccount={(accountId) => {
            dispatchHistoryInteraction({ type: "reset" })
            setSelectedAccountId(accountId)
          }}
          historyState={historyState}
          historyRange={historyRange}
          onHistoryRangeChange={(range) => {
            dispatchHistoryInteraction({ type: "reset" })
            setHistoryRange(range)
          }}
          historyValueMode={historyValueMode}
          onHistoryValueModeChange={setHistoryValueMode}
          selectedHistoryPoint={selectedHistoryPoint}
          isHistoryPointPinned={historyInteraction.pinnedPoint !== null}
          onPreviewHistoryPoint={(point) =>
            dispatchHistoryInteraction(
              point === null ? { type: "leave" } : { type: "preview", point }
            )
          }
          onSelectHistoryPoint={(point) =>
            dispatchHistoryInteraction({ type: "toggle-pin", point })
          }
          onClearHistoryPoint={() => dispatchHistoryInteraction({ type: "reset" })}
        />
      )}
    </div>
  )
}

type CurrentMetadataProps = {
  current: Extract<PortfolioPageState, { status: "ready" }>["current"]
}

function CurrentMetadata({ current }: CurrentMetadataProps) {
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-1 rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
      <span>Aktuální k: {formatSnapshotTimestamp(current.asOf)}</span>
      <span>Denní baseline: {formatSnapshotTimestamp(current.baselineTimestamp)}</span>
      <span>Měna: {current.currency}</span>
    </div>
  )
}

type ReadyPortfolioProps = {
  state: Extract<PortfolioPageState, { status: "ready" }>
  model: ReturnType<typeof buildPortfolioPageModel>
  selectedAccountId: string | null
  selectedAccount: ReturnType<typeof selectPortfolioAccountView>
  onSelectAccount: (accountId: string | null) => void
  historyState: PortfolioHistoryLoadResult | Readonly<{ status: "idle" | "loading" }>
  historyRange: SnapshotPortfolioHistoryRange
  onHistoryRangeChange: (range: SnapshotPortfolioHistoryRange) => void
  historyValueMode: PortfolioHistoryValueMode
  onHistoryValueModeChange: (mode: PortfolioHistoryValueMode) => void
  selectedHistoryPoint: SnapshotPortfolioHistoryPoint | null
  isHistoryPointPinned: boolean
  onPreviewHistoryPoint: (point: SnapshotPortfolioHistoryPoint | null) => void
  onSelectHistoryPoint: (point: SnapshotPortfolioHistoryPoint) => void
  onClearHistoryPoint: () => void
}

function ReadyPortfolio({
  state,
  model,
  selectedAccountId,
  selectedAccount,
  onSelectAccount,
  historyState,
  historyRange,
  onHistoryRangeChange,
  historyValueMode,
  onHistoryValueModeChange,
  selectedHistoryPoint,
  isHistoryPointPinned,
  onPreviewHistoryPoint,
  onSelectHistoryPoint,
  onClearHistoryPoint,
}: ReadyPortfolioProps) {
  const view = selectedAccount ?? model.aggregate
  const historyData =
    historyState.status === "ready" ||
    historyState.status === "rebuilding" ||
    historyState.status === "failed" ||
    historyState.status === "empty"
      ? historyState.data
      : null
  const displayHistoryPoint = selectedHistoryPoint
  const selectedCurrency = displayHistoryPoint
    ? (historyData?.currency ?? view.currency)
    : view.currency
  const allocationItems = displayHistoryPoint
    ? (displayHistoryPoint.positions ?? []).map((position) => ({
        key: position.listingId,
        name: position.symbol,
        allocationPct: position.allocationPct,
      }))
    : view.allocations
  const summaryCards: ReadonlyArray<readonly [string, string | null]> = displayHistoryPoint
    ? [
        ["Celková hodnota", displayHistoryPoint.netWorthValue],
        ["Hodnota investic", displayHistoryPoint.investmentValue],
        ["Nákladová báze investic", displayHistoryPoint.investmentCostBasis ?? null],
        ["Hotovost", displayHistoryPoint.cashValue],
        ["Závazky", displayHistoryPoint.liabilitiesValue],
        ["Čisté vklady", displayHistoryPoint.netInvestedValue ?? null],
        ["Realizované P/L", displayHistoryPoint.realizedPnlValue ?? null],
        ["Nerealizované P/L", displayHistoryPoint.unrealizedPnlValue ?? null],
      ]
    : [
        ["Celková hodnota", view.summary.totalValue],
        ["Hodnota investic", view.summary.investmentValue],
        ["Nákladová báze investic", view.summary.investmentCostBasis],
        ["Hotovost", view.summary.cashValue],
        ["Závazky", view.summary.liabilitiesValue],
        ["Čisté vklady", view.summary.netDepositsValue],
        ["Realizované P/L", view.summary.realizedPnlValue],
        ["Nerealizované P/L", view.summary.unrealizedPnlValue],
      ]

  return (
    <>
      <CurrentMetadata current={state.current} />
      <div
        className={`flex min-h-[50px] items-center justify-between rounded-lg border px-4 py-3 text-sm ${
          selectedHistoryPoint
            ? "border-blue-200 bg-blue-50 text-blue-900"
            : "border-gray-200 bg-gray-50 text-gray-600"
        }`}
      >
        <span>
          {selectedHistoryPoint
            ? `${isHistoryPointPinned ? "Připnutý historický stav" : "Náhled historického stavu"}: ${formatSnapshotTimestamp(selectedHistoryPoint.timestamp)}`
            : `Aktuální stav: ${formatSnapshotTimestamp(state.current.asOf)}`}
        </span>
        {isHistoryPointPinned && (
          <button type="button" className="underline" onClick={onClearHistoryPoint}>
            Zpět na aktuální stav
          </button>
        )}
      </div>

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

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {summaryCards.map(([label, value]) => (
          <div
            key={label}
            className="min-h-[92px] min-w-0 rounded-xl border border-gray-200 bg-white p-5"
          >
            <p className="mb-1 text-sm text-gray-500">{label}</p>
            <p className="break-all text-xl font-semibold">
              {value === null ? "—" : formatSnapshotAmount(value, selectedCurrency)}
            </p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SnapshotCurrencyBreakdown
          title="Hotovost podle měny"
          emptyMessage="Snapshot neobsahuje žádnou hotovost podle měny."
          unavailableMessage={
            displayHistoryPoint
              ? "Historická hodnota není dostupná."
              : "Rozpad hotovosti podle měny není pro aktuální snapshot dostupný."
          }
          items={
            displayHistoryPoint
              ? (displayHistoryPoint.cashByCurrency?.map(({ currency, value }) => ({
                  currency,
                  amount: value,
                })) ?? null)
              : view.summary.cashByCurrency
          }
        />
        <SnapshotCurrencyBreakdown
          title="Čisté vklady podle měny"
          emptyMessage="Snapshot neobsahuje žádné čisté vklady podle měny."
          unavailableMessage={
            displayHistoryPoint
              ? "Historická hodnota není dostupná."
              : "Rozpad čistých vkladů podle měny není pro aktuální snapshot dostupný."
          }
          items={
            displayHistoryPoint
              ? (displayHistoryPoint.netInvestedByCurrency?.map(({ currency, value }) => ({
                  currency,
                  amount: value,
                })) ?? null)
              : view.summary.netDepositsByCurrency
          }
        />
      </div>

      <section
        className="rounded-xl border border-gray-200 bg-white p-6"
        aria-labelledby="portfolio-history-heading"
      >
        <h2 id="portfolio-history-heading" className="mb-1 text-lg font-medium">
          {selectedAccountId === null
            ? "Historie celého portfolia"
            : `Historie účtu ${selectedAccount?.label ?? ""}`}
        </h2>
        <p className="mb-4 text-sm text-gray-500">
          {selectedAccountId === null
            ? "Historie je souhrnná pro všechny účty."
            : "Historie odpovídá právě vybranému účtu."}
        </p>
        {historyState.status === "loading" && (
          <p role="status" className="py-12 text-center text-sm text-gray-500">
            Načítám historii portfolia…
          </p>
        )}
        {historyState.status === "error" && (
          <p role="alert" className="py-12 text-center text-sm text-red-700">
            {historyState.message}
          </p>
        )}
        {historyState.status === "rebuilding" && (
          <p
            role="status"
            className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
          >
            Historie se právě přepočítává. Zobrazené body pocházejí z poslední bezpečně publikované
            generace, pokud je k dispozici.
          </p>
        )}
        {historyState.status === "failed" && (
          <p
            role="alert"
            className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
          >
            Poslední přepočet historie selhal. Zobrazené body pocházejí z poslední kompletní
            publikované generace, pokud je k dispozici.
          </p>
        )}
        {(historyState.status === "ready" ||
          historyState.status === "rebuilding" ||
          historyState.status === "failed" ||
          historyState.status === "empty") && (
          <PortfolioLineChart
            points={historyState.data.points}
            currency={historyState.data.currency}
            range={historyRange}
            onRangeChange={onHistoryRangeChange}
            valueMode={historyValueMode}
            onValueModeChange={onHistoryValueModeChange}
            preferredResolutionMinutes={historyState.data.preferredResolutionMinutes ?? undefined}
            resolutions={historyState.data.resolutions}
            coverage={historyState.data.coverage}
            onPointPreview={onPreviewHistoryPoint}
            onPointSelect={onSelectHistoryPoint}
          />
        )}
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="rounded-xl border border-gray-200 bg-white p-6 lg:col-span-2">
          <h2 className="mb-4 text-lg font-medium">
            {selectedHistoryPoint ? "Pozice k vybranému času" : "Aktuální pozice"}
          </h2>
          <SnapshotHoldingsTable
            positions={view.positions}
            historicalPositions={
              displayHistoryPoint ? (displayHistoryPoint.positions ?? []) : undefined
            }
            currency={selectedCurrency}
          />
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="mb-4 text-lg font-medium">
            {selectedHistoryPoint ? "Alokace k vybranému času" : "Aktuální alokace"}
          </h2>
          <SnapshotAllocationPie items={allocationItems} />
        </div>
      </div>
    </>
  )
}
