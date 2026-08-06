import { createElement, useId } from "react"

import type { PortfolioPageSummary } from "./snapshot-page-model"
import { formatSnapshotDecimal } from "./snapshot-page-format"

type CurrencyAmount = PortfolioPageSummary["cashByCurrency"][number]

type SnapshotCurrencyBreakdownProps = Readonly<{
  title: string
  emptyMessage: string
  items: readonly CurrencyAmount[]
}>

export function SnapshotCurrencyBreakdown({
  title,
  emptyMessage,
  items,
}: SnapshotCurrencyBreakdownProps) {
  const headingId = useId()

  const content =
    items.length === 0
      ? createElement("p", { className: "mt-3 text-sm text-gray-500" }, emptyMessage)
      : createElement(
          "dl",
          { className: "mt-3 divide-y divide-gray-100" },
          items.map((item) =>
            createElement(
              "div",
              {
                key: item.currency,
                className: "flex items-baseline justify-between gap-4 py-2 first:pt-0 last:pb-0",
              },
              createElement("dt", { className: "font-medium text-gray-700" }, item.currency),
              createElement(
                "dd",
                {
                  className: "break-all text-right font-mono text-sm tabular-nums text-gray-900",
                },
                formatSnapshotDecimal(item.amount)
              )
            )
          )
        )

  return createElement(
    "section",
    {
      "aria-labelledby": headingId,
      className: "rounded-xl border border-gray-200 bg-white p-5",
    },
    createElement("h2", { id: headingId, className: "text-lg font-medium text-gray-900" }, title),
    content
  )
}
