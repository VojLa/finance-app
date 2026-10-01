"use client"

import { createElement, useId, useRef } from "react"

import type { PortfolioPageSummary } from "./snapshot-page-model"
import { formatSnapshotExactDecimal, UNAVAILABLE_COST_BASIS_LABEL } from "./snapshot-page-format"

type CurrencyAmount = PortfolioPageSummary["cashByCurrency"][number]

type SnapshotCurrencyBreakdownProps = Readonly<{
  title: string
  emptyMessage: string
  unavailableMessage?: string
  items: readonly CurrencyAmount[] | null
}>

export function splitCurrencyBreakdownItems(items: readonly CurrencyAmount[]) {
  return {
    visible: items.slice(0, 3),
    remaining: items.slice(3),
  }
}

function CurrencyRows({ items }: { items: readonly CurrencyAmount[] }) {
  return createElement(
    "dl",
    { className: "divide-y divide-gray-100" },
    items.map((item) =>
      createElement(
        "div",
        {
          key: item.currency,
          className: "flex h-9 items-baseline justify-between gap-4 py-2 first:pt-0 last:pb-0",
        },
        createElement("dt", { className: "font-medium text-gray-700" }, item.currency),
        createElement(
          "dd",
          {
            className: "break-all text-right font-mono text-sm tabular-nums text-gray-900",
          },
          formatSnapshotExactDecimal(item.amount)
        )
      )
    )
  )
}

export function SnapshotCurrencyBreakdown({
  title,
  emptyMessage,
  unavailableMessage = UNAVAILABLE_COST_BASIS_LABEL,
  items,
}: SnapshotCurrencyBreakdownProps) {
  const headingId = useId()
  const dialogId = useId()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const split = items === null ? null : splitCurrencyBreakdownItems(items)

  const visibleContent =
    items === null
      ? createElement("p", { className: "text-sm text-amber-700" }, unavailableMessage)
      : items.length === 0
        ? createElement("p", { className: "text-sm text-gray-500" }, emptyMessage)
        : createElement(CurrencyRows, { items: split?.visible ?? [] })
  const remainingCount = split?.remaining.length ?? 0

  return createElement(
    "section",
    {
      "aria-labelledby": headingId,
      className: "flex h-[220px] flex-col rounded-xl border border-gray-200 bg-white p-5",
    },
    createElement("h2", { id: headingId, className: "text-lg font-medium text-gray-900" }, title),
    createElement("div", { className: "mt-3 h-[108px] overflow-hidden" }, visibleContent),
    createElement(
      "div",
      { className: "mt-auto flex min-h-8 items-end" },
      remainingCount > 0
        ? createElement(
            "button",
            {
              type: "button",
              "aria-haspopup": "dialog",
              "aria-controls": dialogId,
              onClick: () => dialogRef.current?.showModal(),
              className: "text-sm font-medium text-blue-600 hover:underline",
            },
            `Zobrazit další měny (${remainingCount})`
          )
        : null
    ),
    remainingCount > 0
      ? createElement(
          "dialog",
          {
            ref: dialogRef,
            id: dialogId,
            "aria-labelledby": `${dialogId}-heading`,
            className:
              "w-full max-w-md rounded-xl border border-gray-200 bg-white p-0 shadow-xl backdrop:bg-black/30",
          },
          createElement(
            "div",
            { className: "p-6" },
            createElement(
              "div",
              { className: "mb-4 flex items-center justify-between gap-4" },
              createElement(
                "h3",
                { id: `${dialogId}-heading`, className: "text-lg font-medium text-gray-900" },
                `${title} – další měny`
              ),
              createElement(
                "form",
                { method: "dialog" },
                createElement(
                  "button",
                  {
                    type: "submit",
                    className: "rounded-md px-2 py-1 text-gray-500 hover:bg-gray-100",
                  },
                  "Zavřít"
                )
              )
            ),
            createElement(CurrencyRows, { items: split?.remaining ?? [] })
          )
        )
      : null
  )
}
