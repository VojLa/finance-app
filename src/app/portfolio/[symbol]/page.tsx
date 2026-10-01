"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { useEffect, useState } from "react"

import { fmt } from "@/lib/format"
import { requestSymbolDetail } from "@/modules/investments/investment-client"
import type { SymbolDetail } from "@/modules/investments/investment-contract"

const TYPE_LABELS: Record<string, string> = {
  buy: "Nákup",
  sell: "Prodej",
  dividend: "Dividenda",
  interest: "Úrok",
  deposit: "Vklad",
  withdrawal: "Výběr",
  currency_conversion: "Konverze",
  staking_reward: "Staking",
  airdrop: "Airdrop",
  fee: "Poplatek",
  transfer: "Převod",
}

const TYPE_BADGE_COLORS: Record<string, string> = {
  buy: "bg-blue-50 text-blue-700",
  sell: "bg-orange-50 text-orange-700",
  dividend: "bg-green-50 text-green-700",
}

function number(value: string | null): number | null {
  return value === null ? null : Number(value)
}

const TRACE_STATUS: Record<string, { label: string; style: string }> = {
  ok: { label: "OK", style: "bg-green-50 text-green-700" },
  unresolved: { label: "Nevyřešená identita", style: "bg-amber-50 text-amber-700" },
  conflict: { label: "Rozpor v evidenci", style: "bg-red-50 text-red-700" },
  stale: { label: "Zastaralá cena", style: "bg-amber-50 text-amber-700" },
  unavailable: { label: "Nedostupné podklady", style: "bg-gray-100 text-gray-600" },
}

function evidence(value: string | number | null): string {
  return value === null ? "Nedostupné" : String(value)
}

export default function SymbolPage() {
  const { symbol } = useParams<{ symbol: string }>()
  const [detail, setDetail] = useState<SymbolDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    requestSymbolDetail(symbol)
      .then((value) => {
        if (active) setDetail(value)
      })
      .catch((loadError: unknown) => {
        if (active) {
          setDetail(null)
          setError(
            loadError instanceof Error ? loadError.message : "Detail symbolu se nepodařilo načíst."
          )
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [symbol])

  if (loading) return <div className="py-12 text-center text-gray-400">Načítám...</div>
  if (error)
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-red-700">{error}</div>
    )
  if (!detail || (detail.positions.length === 0 && detail.events.length === 0))
    return (
      <div className="py-12 text-center">
        <p className="mb-4 text-gray-500">Symbol {symbol} nebyl v dostupných účtech nalezen.</p>
        <Link href="/portfolio" className="text-blue-600 hover:underline">
          ← Portfolio
        </Link>
      </div>
    )

  const firstPosition = detail.positions[0]

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/portfolio" className="text-sm text-gray-400 hover:text-gray-600">
          ← Portfolio
        </Link>
        <h1 className="text-2xl font-semibold">{detail.symbol}</h1>
        {firstPosition?.name && <span className="text-lg text-gray-500">{firstPosition.name}</span>}
        {firstPosition && (
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs uppercase text-gray-500">
            {firstPosition.assetType}
          </span>
        )}
      </div>

      {detail.positions.map((position) => (
        <section key={position.id} className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <h2 className="font-medium">{position.accountName}</h2>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${TRACE_STATUS[position.traceStatus]?.style ?? TRACE_STATUS.unavailable.style}`}
            >
              {TRACE_STATUS[position.traceStatus]?.label ?? TRACE_STATUS.unavailable.label}
            </span>
          </div>
          <div className="mb-5 grid gap-3 rounded-lg bg-gray-50 p-4 text-sm md:grid-cols-2 xl:grid-cols-6">
            <div>
              <p className="mb-1 text-xs text-gray-500">Broker → aktivum</p>
              <p className="text-gray-600">{position.symbol}</p>
              <p className="font-medium">{evidence(position.assetName ?? position.name)}</p>
              <p className="text-gray-600">
                {evidence(position.assetIsin)} · {position.assetType}
              </p>
              <p className="break-all text-xs text-gray-400">ID: {evidence(position.assetId)}</p>
            </div>
            <div>
              <p className="mb-1 text-xs text-gray-500">Požadovaný listing</p>
              <p className="font-medium">{evidence(position.listingSymbol)}</p>
              <p className="text-gray-600">
                {evidence(position.listingExchange)} · {evidence(position.listingMic)} ·{" "}
                {evidence(position.listingCurrency)}
              </p>
              <p className="break-all text-xs text-gray-400">
                ID: {position.requestedListingId} · priorita: {evidence(position.listingBasePriority)}
              </p>
            </div>
            <div>
              <p className="mb-1 text-xs text-gray-500">Vybraný listing</p>
              <p className="break-all font-medium">{evidence(position.selectedListingId)}</p>
              <p className="text-gray-600">
                Priorita: {evidence(position.selectedBasePriority)} · stav: {evidence(position.selectedHealth)}
              </p>
              <p className="text-xs text-gray-500">
                Výběr: {evidence(position.selectionReason)} · důvod změny: {evidence(position.fallbackReason)}
              </p>
            </div>
            <div>
              <p className="mb-1 text-xs text-gray-500">Skutečný tržní zdroj</p>
              <p className="font-medium">{evidence(position.selectedProvider)}</p>
              <p className="break-all text-gray-600">{evidence(position.selectedProviderSymbol)}</p>
            </div>
            <div>
              <p className="mb-1 text-xs text-gray-500">Uložená cena</p>
              <p className="font-medium">
                {position.priceAmount === null
                  ? "Nedostupné"
                  : `${position.priceAmount} ${evidence(position.priceCurrency)}`}
              </p>
              <p className="text-gray-600">
                {evidence(position.priceSource)} · {evidence(position.priceProviderSymbol)}
              </p>
              <p className="text-xs text-gray-400">
                {position.priceTimestamp
                  ? new Date(position.priceTimestamp).toLocaleString("cs-CZ")
                  : "Nedostupné datum"}
              </p>
              <p className="break-all text-xs text-gray-400">
                Snapshot: {evidence(position.priceSnapshotId)} · čerstvost: {position.priceFreshness}
              </p>
            </div>
            <div>
              <p className="mb-1 text-xs text-gray-500">Aktuální pozice</p>
              <p className="font-medium">{fmt(Number(position.quantity), 6)} ks</p>
              <p className="text-gray-600">
                {position.currentValue === null
                  ? "Hodnota nedostupná"
                  : `${fmt(Number(position.currentValue))} ${position.currency}`}
              </p>
              <p className="text-xs text-gray-400">
                FX reference: {evidence(position.fxEvidenceId)} · kurz: {evidence(position.fxRate)} ·
                přepočtená hodnota: {evidence(position.convertedValue)}
              </p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <div>
              <p className="text-sm text-gray-500">Množství</p>
              <p className="font-mono text-lg font-semibold">{fmt(Number(position.quantity), 6)}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Průměrná nákupní cena</p>
              <p className="font-mono text-lg font-semibold">
                {position.avgBuyPrice === null
                  ? "Nedostupné"
                  : `${fmt(Number(position.avgBuyPrice))} ${position.currency}`}
              </p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Aktuální cena</p>
              <p className="font-mono text-lg font-semibold">
                {number(position.currentPrice) === null
                  ? "—"
                  : `${fmt(Number(position.currentPrice))} ${position.currency}`}
              </p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Aktuální hodnota</p>
              <p className="font-mono text-lg font-semibold">
                {number(position.currentValue) === null
                  ? "—"
                  : `${fmt(Number(position.currentValue))} ${position.currency}`}
              </p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Nerealizovaný výsledek</p>
              <p className="font-mono text-lg font-semibold">
                {number(position.unrealizedPnl) === null
                  ? "—"
                  : `${fmt(Number(position.unrealizedPnl))} ${position.currency}`}
              </p>
            </div>
          </div>
        </section>
      ))}

      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="mb-4 text-lg font-medium">Historie transakcí ({detail.events.length})</h2>
        {detail.events.length === 0 ? (
          <p className="text-sm text-gray-400">Žádné transakce.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-left text-gray-500">
                  <th className="pb-3 font-medium">Datum</th>
                  <th className="pb-3 font-medium">Účet</th>
                  <th className="pb-3 font-medium">Typ</th>
                  <th className="pb-3 text-right font-medium">Množství</th>
                  <th className="pb-3 text-right font-medium">Cena / ks</th>
                  <th className="pb-3 text-right font-medium">Celkem</th>
                  <th className="pb-3 text-right font-medium">Poplatek</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {detail.events.map((event) => (
                  <tr key={event.id} className="hover:bg-gray-50">
                    <td className="py-2.5 text-gray-500">
                      {new Date(event.date).toLocaleDateString("cs-CZ")}
                    </td>
                    <td className="py-2.5 text-gray-500">{event.accountName}</td>
                    <td className="py-2.5">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${TYPE_BADGE_COLORS[event.type] ?? "bg-gray-50 text-gray-600"}`}
                      >
                        {TYPE_LABELS[event.type] ?? event.type}
                      </span>
                    </td>
                    <td className="py-2.5 text-right font-mono">
                      {event.quantity === null ? "—" : fmt(Number(event.quantity), 6)}
                    </td>
                    <td className="py-2.5 text-right font-mono text-gray-500">
                      {event.pricePerUnit === null
                        ? "—"
                        : `${fmt(Number(event.pricePerUnit))} ${event.priceCurrency ?? ""}`}
                    </td>
                    <td className="py-2.5 text-right font-mono font-medium">
                      {event.totalAmount === null
                        ? "—"
                        : `${fmt(Number(event.totalAmount))} ${event.totalCurrency ?? ""}`}
                    </td>
                    <td className="py-2.5 text-right font-mono text-gray-400">
                      {event.fee === null
                        ? "—"
                        : `${fmt(Number(event.fee))} ${event.feeCurrency ?? ""}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
