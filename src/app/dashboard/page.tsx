"use client"

import Link from "next/link"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { OperationalDashboardSections } from "@/modules/dashboard/OperationalDashboardSections"
import { SnapshotAccountCards } from "@/modules/dashboard/SnapshotAccountCards"
import { SnapshotAssetAllocationChart } from "@/modules/dashboard/SnapshotAssetAllocationChart"
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

function EmptyFinancialState({
  state,
}: {
  state: Extract<DashboardFinancialState, { status: "empty" }>
}) {
  return (
    <section
      aria-labelledby="financial-overview-heading"
      className="rounded-lg border border-gray-200 bg-white p-6"
    >
      <h2 id="financial-overview-heading" className="text-lg font-medium">
        Finanční přehled
      </h2>
      <p className="mt-2 text-sm text-gray-600">
        Zatím nemáte žádný účet, pro který by bylo možné vytvořit finanční snapshot.
      </p>
      <p className="mt-2 text-xs text-gray-400">
        Obnoveno {formatSnapshotTimestamp(state.refresh.timestamp)} · {state.refresh.currency}
      </p>
      <Link
        href="/accounts"
        className="mt-4 inline-flex rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
      >
        Přidat účet
      </Link>
    </section>
  )
}

export default function DashboardPage() {
  const initialLoadStarted = useRef(false)
  const [financialState, setFinancialState] = useState<DashboardFinancialState>({
    status: "loading",
  })
  const [operationalState, setOperationalState] = useState<DashboardOperationalState>({
    status: "loading",
  })
  const [financialRefreshInProgress, setFinancialRefreshInProgress] = useState(false)

  const loadFinancialOverview = useCallback(async (isRefresh = false) => {
    if (isRefresh) setFinancialRefreshInProgress(true)
    try {
      setFinancialState(await requestDashboardFinancialState())
    } finally {
      if (isRefresh) setFinancialRefreshInProgress(false)
    }
  }, [])

  useEffect(() => {
    if (initialLoadStarted.current) return
    initialLoadStarted.current = true

    void loadFinancialOverview()
    void requestOperationalDashboardState().then(setOperationalState)
  }, [loadFinancialOverview])

  const financialModel = useMemo(
    () =>
      financialState.status === "ready"
        ? buildSnapshotDashboardModel(financialState.data)
        : undefined,
    [financialState]
  )

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
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
          onClick={() => void loadFinancialOverview(true)}
          className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {financialRefreshInProgress ? "Aktualizuji…" : "Aktualizovat finanční přehled"}
        </button>
      </header>

      {financialState.status === "loading" && (
        <SectionSkeleton label="Načítání finančního přehledu" />
      )}
      {financialState.status === "error" && <FinancialError state={financialState} />}
      {financialState.status === "empty" && <EmptyFinancialState state={financialState} />}
      {financialState.status === "ready" && financialModel && (
        <section aria-labelledby="financial-overview-heading" className="space-y-6">
          <div>
            <h2 id="financial-overview-heading" className="text-xl font-semibold">
              Finanční přehled
            </h2>
            <p className="mt-1 text-xs text-gray-400">
              Snapshot {formatSnapshotTimestamp(financialModel.timestamp)} ·{" "}
              {financialModel.currency} · verze výpočtu {financialModel.calculationVersion}
            </p>
          </div>
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
      {operationalState.status === "ready" && (
        <OperationalDashboardSections data={operationalState.data} />
      )}
    </div>
  )
}
