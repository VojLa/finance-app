"use client"

import Link from "next/link"
import dynamic from "next/dynamic"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { type PortfolioHistoryValueMode } from "@/components/charts/PortfolioLineChart"
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
  const [selectedHistoryPoint, setSelectedHistoryPoint] =
    useState<SnapshotPortfolioHistoryPoint | null>(null)
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
    setSelectedHistoryPoint(null)
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
        <div role="status" className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
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
            setSelectedHistoryPoint(null)
            setSelectedAccountId(accountId)
          }}
          historyState={historyState}
          historyRange={historyRange}
          onHistoryRangeChange={(range) => {
            setSelectedHistoryPoint(null)
            setHistoryRange(range)
          }}
          historyValueMode={historyValueMode}
          onHistoryValueModeChange={setHistoryValueMode}
          selectedHistoryPoint={selectedHistoryPoint}
          onSelectHistoryPoint={setSelectedHistoryPoint}
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
  onSelectHistoryPoint: (point: SnapshotPortfolioHistoryPoint | null) => void
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
  onSelectHistoryPoint,
}: ReadyPortfolioProps) {
  const view = selectedAccount ?? model.aggregate
  const showAccount = view.scope === "aggregate" && model.accounts.length > 1
  const selectedCurrency = selectedHistoryPoint ? historyState.status === "ready"
    ? historyState.data.currency
    : view.currency : view.currency
  const summaryCards: ReadonlyArray<readonly [string, string | null]> = selectedHistoryPoint
    ? [
        ["Celková hodnota", selectedHistoryPoint.netWorthValue],
        ["Hodnota investic", selectedHistoryPoint.investmentValue],
        ["Nákladová báze investic", null],
        ["Hotovost", selectedHistoryPoint.cashValue],
        ["Závazky", selectedHistoryPoint.liabilitiesValue],
        ["Čisté vklady", selectedHistoryPoint.netInvestedValue ?? null],
        ["Realizované P/L", selectedHistoryPoint.realizedPnlValue ?? null],
        ["Nerealizované P/L", selectedHistoryPoint.unrealizedPnlValue ?? null],
      ]
    : [
        ["Celková hodnota", view.summary.totalValue],
        ["Hodnota investic", view.summary.investmentValue],
        ["Nákladová báze investic", view.summary.investmentCostBasis],
        ["Hotovost", view.summary.cashValue],
        ["Čisté vklady", view.summary.netDepositsValue],
        ["Realizované P/L", view.summary.realizedPnlValue],
        ["Nerealizované P/L", view.summary.unrealizedPnlValue],
      ]

  return (
    <>
      <CurrentMetadata current={state.current} />
      {selectedHistoryPoint && (
        <div className="flex items-center justify-between rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
          <span>Historický stav: {formatSnapshotTimestamp(selectedHistoryPoint.timestamp)}</span>
          <button type="button" className="underline" onClick={() => onSelectHistoryPoint(null)}>
            Zpět na aktuální stav
          </button>
        </div>
      )}

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
          <div key={label} className="min-w-0 rounded-xl border border-gray-200 bg-white p-5">
            <p className="mb-1 text-sm text-gray-500">{label}</p>
            <p className="break-all text-xl font-semibold">
              {value === null ? "—" : formatSnapshotAmount(value, selectedCurrency)}
            </p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {selectedHistoryPoint && selectedHistoryPoint.cashByCurrency === undefined ? (
          <section className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="text-lg font-medium">Hotovost podle měny</h2>
            <p className="mt-3 text-sm text-amber-700">Historická hodnota není dostupná.</p>
          </section>
        ) : (
          <SnapshotCurrencyBreakdown
            title="Hotovost podle měny"
            emptyMessage="Snapshot neobsahuje žádnou hotovost podle měny."
            items={selectedHistoryPoint
              ? selectedHistoryPoint.cashByCurrency!.map(({ currency, value }) => ({ currency, amount: value }))
              : view.summary.cashByCurrency}
          />
        )}
        {selectedHistoryPoint && selectedHistoryPoint.netInvestedByCurrency === undefined ? (
          <section className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="text-lg font-medium">Čisté vklady podle měny</h2>
            <p className="mt-3 text-sm text-amber-700">Historická hodnota není dostupná.</p>
          </section>
        ) : (
          <SnapshotCurrencyBreakdown
            title="Čisté vklady podle měny"
            emptyMessage="Snapshot neobsahuje žádné čisté vklady podle měny."
            items={selectedHistoryPoint
              ? selectedHistoryPoint.netInvestedByCurrency!.map(({ currency, value }) => ({ currency, amount: value }))
              : view.summary.netDepositsByCurrency}
          />
        )}
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
            onPointSelect={onSelectHistoryPoint}
          />
        )}
      </section>

      {selectedHistoryPoint ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white p-6 lg:col-span-2">
            <h2 className="mb-4 text-lg font-medium">Pozice k vybranému času</h2>
            {(selectedHistoryPoint.positions?.length ?? 0) === 0 ? (
              <p className="text-sm text-gray-500">Snapshot neobsahuje žádné pozice.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-gray-500">
                    <th className="py-2">Instrument</th>
                    <th>Počet</th>
                    <th>Hodnota</th>
                    <th>Nákladová báze</th>
                    <th>Alokace</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedHistoryPoint.positions?.map((position) => (
                    <tr key={position.listingId} className="border-b last:border-0">
                      <td className="py-2 font-medium">{position.symbol}</td>
                      <td>{position.quantity}</td>
                      <td>{formatSnapshotAmount(position.value, selectedCurrency)}</td>
                      <td>
                        {position.costBasis === undefined
                          ? "—"
                          : formatSnapshotAmount(position.costBasis, selectedCurrency)}
                      </td>
                      <td>{position.allocationPct} %</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <h2 className="mb-4 text-lg font-medium">Alokace k vybranému času</h2>
            <div className="space-y-3">
              {selectedHistoryPoint.positions?.map((position) => (
                <div key={position.listingId}>
                  <div className="mb-1 flex justify-between text-sm">
                    <span>{position.symbol}</span>
                    <span>{position.allocationPct} %</span>
                  </div>
                  <div className="h-2 rounded bg-gray-100">
                    <div
                      className="h-2 rounded bg-emerald-500"
                      style={{ width: `${Math.min(100, Number(position.allocationPct))}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
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
      )}
    </>
  )
}
