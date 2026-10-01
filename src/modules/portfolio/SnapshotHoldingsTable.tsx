"use client"

import Link from "next/link"
import { useId, useMemo, useRef, useState } from "react"

import type { PortfolioPagePosition } from "./snapshot-page-model"
import type { SnapshotPortfolioHistoryPoint } from "./snapshot-history-contract"
import {
  formatSnapshotAmount,
  formatSnapshotPercentage,
  formatSnapshotQuantity,
  snapshotPercentageTone,
} from "./snapshot-page-format"
import {
  sortSnapshotHoldingRows,
  type SnapshotHoldingRow,
  type SnapshotHoldingSort,
  type SnapshotHoldingSortKey,
} from "./snapshot-holdings-table"

type Props = {
  positions: readonly PortfolioPagePosition[]
  historicalPositions?: NonNullable<SnapshotPortfolioHistoryPoint["positions"]>
  currency: string
}

const VISIBLE_ROWS = 5
const POSITION_ROW_CLASS = {
  positive: "border-b bg-emerald-50 text-emerald-900 last:border-0",
  negative: "border-b bg-red-50 text-red-900 last:border-0",
  neutral: "border-b bg-gray-50 text-gray-700 last:border-0",
  unavailable: "border-b text-gray-700 last:border-0",
} as const
const HEADERS: ReadonlyArray<
  Readonly<{ key: SnapshotHoldingSortKey; label: string; align: "left" | "right" }>
> = [
  { key: "symbol", label: "Instrument", align: "left" },
  { key: "quantity", label: "Počet", align: "right" },
  { key: "value", label: "Hodnota", align: "right" },
  { key: "costBasis", label: "Nákladová báze", align: "right" },
  { key: "unrealizedPnlPct", label: "Zisk / ztráta", align: "right" },
  { key: "allocationPct", label: "Alokace", align: "right" },
]

function HoldingRow({ row, currency }: { row: SnapshotHoldingRow; currency: string }) {
  return (
    <tr className={`h-12 ${POSITION_ROW_CLASS[snapshotPercentageTone(row.unrealizedPnlPct)]}`}>
      <td className="px-2 py-2">
        <Link
          href={`/portfolio/${encodeURIComponent(row.symbol)}`}
          className="font-medium text-blue-600 hover:underline"
        >
          {row.symbol}
        </Link>
      </td>
      <td className="px-2 py-2 text-right font-mono">{formatSnapshotQuantity(row.quantity)}</td>
      <td className="px-2 py-2 text-right font-mono font-medium">
        {formatSnapshotAmount(row.value, currency)}
      </td>
      <td className="px-2 py-2 text-right font-mono text-gray-600">
        {row.costBasis === undefined ? "—" : formatSnapshotAmount(row.costBasis, currency)}
      </td>
      <td className="px-2 py-2 text-right font-mono">
        {row.unrealizedPnlPct === undefined
          ? "—"
          : `${formatSnapshotPercentage(row.unrealizedPnlPct)} %`}
      </td>
      <td className="px-2 py-2 text-right font-mono">
        {formatSnapshotPercentage(row.allocationPct)} %
      </td>
    </tr>
  )
}

function HoldingsTable({
  rows,
  currency,
  sort,
  onSort,
  padToFive,
}: {
  rows: readonly SnapshotHoldingRow[]
  currency: string
  sort: SnapshotHoldingSort
  onSort?: (key: SnapshotHoldingSortKey) => void
  padToFive: boolean
}) {
  const occupiedRows = rows.length === 0 && padToFive ? 1 : rows.length
  const missingRows = VISIBLE_ROWS - occupiedRows
  const placeholders = padToFive && missingRows > 0 ? missingRows : 0
  return (
    <table className="w-full min-w-[760px] table-fixed text-sm">
      <thead>
        <tr className="h-12 border-b border-gray-100 text-gray-500">
          {HEADERS.map((header) => (
            <th
              key={header.key}
              scope="col"
              aria-sort={sort.key === header.key ? sort.direction : "none"}
              className={`${header.align === "right" ? "text-right" : "text-left"} px-2 font-medium`}
            >
              <button
                type="button"
                disabled={onSort === undefined}
                onClick={() => onSort?.(header.key)}
                className="inline-flex items-center gap-1 disabled:cursor-default"
              >
                {header.label}
                {sort.key === header.key && (
                  <span aria-hidden="true">{sort.direction === "ascending" ? "↑" : "↓"}</span>
                )}
              </button>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && padToFive ? (
          <tr className="h-12 border-b text-gray-400">
            <td colSpan={HEADERS.length} className="px-2 text-center">
              Žádné snapshot-backed pozice.
            </td>
          </tr>
        ) : (
          rows.map((row) => <HoldingRow key={row.key} row={row} currency={currency} />)
        )}
        {Array.from({ length: placeholders }).map((_, index) => (
          <tr
            key={`placeholder-${index}`}
            aria-hidden="true"
            className="h-12 border-b last:border-0"
          >
            <td colSpan={HEADERS.length}>&nbsp;</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function SnapshotHoldingsTable({ positions, historicalPositions, currency }: Props) {
  const dialogId = useId()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [sort, setSort] = useState<SnapshotHoldingSort>({
    key: "allocationPct",
    direction: "descending",
  })
  const rows: SnapshotHoldingRow[] = useMemo(
    () =>
      historicalPositions === undefined
        ? positions.map(({ accountId, allocationPct, position }) => ({
            key: `${accountId}:${position.listingId}`,
            listingId: position.listingId,
            symbol: position.symbol,
            quantity: position.quantity,
            value: position.value,
            costBasis: position.costBasis ?? undefined,
            unrealizedPnlPct: position.unrealizedPnlPct ?? undefined,
            allocationPct,
          }))
        : historicalPositions.map((position) => ({
            key: position.listingId,
            listingId: position.listingId,
            symbol: position.symbol,
            quantity: position.quantity,
            value: position.value,
            costBasis: position.costBasis,
            unrealizedPnlPct: position.unrealizedPnlPct,
            allocationPct: position.allocationPct,
          })),
    [historicalPositions, positions]
  )
  const sortedRows = useMemo(() => sortSnapshotHoldingRows(rows, sort), [rows, sort])
  const visibleRows = sortedRows.slice(0, VISIBLE_ROWS)
  const changeSort = (key: SnapshotHoldingSortKey) =>
    setSort((current) => ({
      key,
      direction:
        current.key === key && current.direction === "ascending" ? "descending" : "ascending",
    }))

  return (
    <div className="flex h-[344px] flex-col">
      <div className="h-[288px] overflow-x-auto">
        <HoldingsTable
          rows={visibleRows}
          currency={currency}
          sort={sort}
          onSort={changeSort}
          padToFive
        />
      </div>
      <div className="flex h-14 shrink-0 items-end">
        {sortedRows.length > VISIBLE_ROWS && (
          <button
            type="button"
            aria-haspopup="dialog"
            aria-controls={dialogId}
            onClick={() => dialogRef.current?.showModal()}
            className="text-sm font-medium text-blue-600 hover:underline"
          >
            Zobrazit vše ({sortedRows.length})
          </button>
        )}
      </div>
      <dialog
        ref={dialogRef}
        id={dialogId}
        aria-labelledby={`${dialogId}-heading`}
        className="w-[min(96vw,1100px)] rounded-xl border border-gray-200 bg-white p-0 shadow-xl backdrop:bg-black/30"
      >
        <div className="p-6">
          <div className="mb-4 flex items-center justify-between gap-4">
            <h3 id={`${dialogId}-heading`} className="text-lg font-medium text-gray-900">
              Všechny pozice
            </h3>
            <form method="dialog">
              <button
                type="submit"
                className="rounded-md px-2 py-1 text-gray-500 hover:bg-gray-100"
              >
                Zavřít
              </button>
            </form>
          </div>
          <div className="max-h-[70vh] overflow-auto">
            <HoldingsTable
              rows={sortedRows}
              currency={currency}
              sort={sort}
              onSort={changeSort}
              padToFive={false}
            />
          </div>
        </div>
      </dialog>
    </div>
  )
}
