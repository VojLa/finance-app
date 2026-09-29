"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import dynamic from "next/dynamic"
import { OperationalDashboardSections } from "@/modules/dashboard/OperationalDashboardSections"
import { SnapshotAccountCards } from "@/modules/dashboard/SnapshotAccountCards"
import { SnapshotSummaryCards } from "@/modules/dashboard/SnapshotSummaryCards"
import { SnapshotTopPositions } from "@/modules/dashboard/SnapshotTopPositions"
import {
  requestOperationalDashboardState,
  type DashboardOperationalState,
} from "@/modules/dashboard/operational-dashboard-client"
import {
  requestDashboardFinancialState,
  type DashboardFinancialState,
} from "@/modules/dashboard/snapshot-dashboard-client"
import { buildSnapshotDashboardModel } from "@/modules/dashboard/snapshot-dashboard-model"
import { formatSnapshotTimestamp } from "@/modules/portfolio/snapshot-page-format"
import { resolveSnapshotPublication } from "@/lib/retain-ready-state"
import { createSerializedRefreshGate, runSerializedRefresh } from "@/lib/serialized-refresh"
import {
  isReadModelUpdateForScope,
  READ_MODEL_UPDATED_EVENT,
} from "@/modules/read-models/read-model-version-client"

const SnapshotAssetAllocationChart = dynamic(
  () =>
    import("@/modules/dashboard/SnapshotAssetAllocationChart").then(
      (module) => module.SnapshotAssetAllocationChart
    ),
  {
    ssr: false,
    loading: () => <div className="h-72 animate-pulse rounded-lg bg-gray-100" />,
  }
)

function SectionSkeleton({ label }: { label: string }) {
  return (
    <section aria-label={label} className="space-y-4">
      <div className="h-7 w-64 animate-pulse rounded bg-gray-100" />
      <div className="grid gap-4 md:grid-cols-4">
        {[0, 1, 2, 3].map((item) => (
          <div key={item} className="h-32 animate-pulse rounded-lg bg-gray-100" />
        ))}
      </div>
    </section>
  )
}

function FinancialError({
  state,
}: {
  state: Extract<DashboardFinancialState, { status: "error" }>
}) {
  return (
    <section
      aria-labelledby="financial-overview-heading"
      className="rounded-lg border border-red-200 bg-red-50 p-5"
      role="alert"
    >
      <h2 id="financial-overview-heading" className="font-medium text-red-900">
        Finanční přehled není dostupný
      </h2>
      <p className="mt-1 text-sm text-red-700">{state.message}</p>
    </section>
  )
}

export default function DashboardPage() {
  const initialLoadStarted = useRef(false)
  const financialRefreshGate = useRef(createSerializedRefreshGate())
  const operationalRequestId = useRef(0)
  const [financialState, setFinancialState] = useState<DashboardFinancialState>({
    status: "loading",
  })
  const [operationalState, setOperationalState] = useState<DashboardOperationalState>({
    status: "loading",
  })
  const [financialRefreshInProgress, setFinancialRefreshInProgress] = useState(false)
  const lastReadyFinancialState = useRef<Extract<
    DashboardFinancialState,
    { status: "ready" }
  > | null>(null)
  const [financialRefreshWarning, setFinancialRefreshWarning] = useState<string | null>(null)
  const [operationalRefreshWarning, setOperationalRefreshWarning] = useState<string | null>(null)
  const lastReadyOperationalState = useRef<Extract<DashboardOperationalState, { status: "ready" }> | null>(null)

  const loadFinancialOverview = useCallback(
    (isRefresh = false) =>
      runSerializedRefresh(financialRefreshGate.current, isRefresh, async (activeRefresh) => {
        if (activeRefresh) setFinancialRefreshInProgress(true)
        try {
          const next = await requestDashboardFinancialState()
          const decision = resolveSnapshotPublication(
            next,
            lastReadyFinancialState.current,
            activeRefresh
          )
          lastReadyFinancialState.current = decision.lastReady
          setFinancialRefreshWarning(decision.warning)
          setFinancialState(decision.state)
        } finally {
          if (activeRefresh) setFinancialRefreshInProgress(false)
        }
      }),
    []
  )

  const loadDashboard = useCallback((isRefresh = false) => {
    void loadFinancialOverview(isRefresh)
    const requestId = ++operationalRequestId.current
    void requestOperationalDashboardState().then((next) => {
      if (requestId !== operationalRequestId.current) return
      if (next.status === "error" && isRefresh && lastReadyOperationalState.current !== null) {
        setOperationalRefreshWarning(next.message)
        return
      }
      if (next.status === "ready") lastReadyOperationalState.current = next
      setOperationalRefreshWarning(null)
      setOperationalState(next)
    })
  }, [loadFinancialOverview])

  useEffect(() => {
    if (initialLoadStarted.current) return
    initialLoadStarted.current = true

    loadDashboard()
  }, [loadDashboard])

  useEffect(() => {
    const refreshOnReadModelUpdate = (event: Event) => {
      if (isReadModelUpdateForScope(event, "dashboard")) loadDashboard(true)
    }
    window.addEventListener(READ_MODEL_UPDATED_EVENT, refreshOnReadModelUpdate)
    return () => window.removeEventListener(READ_MODEL_UPDATED_EVENT, refreshOnReadModelUpdate)
  }, [loadDashboard])

  useEffect(() => {
    const refreshOnImportCompleted = () => loadDashboard(true)
    window.addEventListener("finance:import-completed", refreshOnImportCompleted)
    return () => window.removeEventListener("finance:import-completed", refreshOnImportCompleted)
  }, [loadDashboard])

  const financialModel = useMemo(
    () =>
      financialState.status === "ready"
        ? buildSnapshotDashboardModel(financialState.data)
        : undefined,
    [financialState]
  )

  return (
    <div className="space-y-7 pb-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Přehled</h1>
          <p className="mt-1 text-sm text-gray-500">
            {new Date().toLocaleDateString("cs-CZ", {
              month: "long",
              year: "numeric",
            })}
          </p>
        </div>
        <button
          type="button"
          disabled={financialState.status === "loading" || financialRefreshInProgress}
          onClick={() => loadDashboard(true)}
          className="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {financialRefreshInProgress ? "Aktualizuji…" : "Aktualizovat"}
        </button>
      </header>

      {financialState.status === "loading" && (
        <SectionSkeleton label="Načítání finančního přehledu" />
      )}
      {financialState.status === "error" && <FinancialError state={financialState} />}
      {financialRefreshWarning !== null && (
        <section
          className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
          role="status"
        >
          Finanční přehled zůstává z posledního dokončeného snapshotu. Aktualizaci se nepodařilo
          dokončit: {financialRefreshWarning}
        </section>
      )}
      {financialState.status === "ready" && financialState.current.isStale && (
        <section className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900" role="status">
          Ceny jsou starší než 30 minut. Zobrazuji poslední bezpečně publikovaný stav oceněný k{" "}
          {formatSnapshotTimestamp(financialState.current.valuationTimestamp)}.
        </section>
      )}
      {financialState.status === "ready" && financialModel && (
        <section aria-labelledby="financial-overview-heading" className="space-y-6">
          <p id="financial-overview-heading" className="text-xs text-gray-400">
            Finanční stav k {formatSnapshotTimestamp(financialModel.timestamp)} ·{" "}
            {financialModel.currency}
          </p>
          <SnapshotSummaryCards model={financialModel} />
          <SnapshotAccountCards model={financialModel} />
          <div className="grid gap-6 xl:grid-cols-2">
            <SnapshotAssetAllocationChart model={financialModel} />
            <SnapshotTopPositions model={financialModel} />
          </div>
        </section>
      )}

      {operationalState.status === "loading" && (
        <SectionSkeleton label="Načítání provozního přehledu" />
      )}
      {operationalState.status === "error" && (
        <section className="rounded-lg border border-amber-200 bg-amber-50 p-5" role="alert">
          <h2 className="font-medium text-amber-900">Provozní přehled není dostupný</h2>
          <p className="mt-1 text-sm text-amber-700">{operationalState.message}</p>
        </section>
      )}
      {operationalRefreshWarning !== null && (
        <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          Provozní přehled zůstává z posledního načtení: {operationalRefreshWarning}
        </p>
      )}
      {operationalState.status === "ready" && (
        <OperationalDashboardSections data={operationalState.data} />
      )}
    </div>
  )
}
