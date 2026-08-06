import { createRequire } from "node:module"

import { createElement } from "react"
import type { ReactNode } from "react"
import { describe, expect, it } from "vitest"

import { SnapshotCurrencyBreakdown } from "./SnapshotCurrencyBreakdown"

const { renderToStaticMarkup } = createRequire(import.meta.url)("react-dom/server") as {
  renderToStaticMarkup(node: ReactNode): string
}

const ITEMS = [
  { currency: "CZK", amount: "10000.000000" },
  { currency: "EUR", amount: "500.000000" },
  { currency: "USD", amount: "-50.000000" },
] as const

function render(items: readonly { currency: string; amount: string }[]) {
  return renderToStaticMarkup(
    createElement(SnapshotCurrencyBreakdown, {
      title: "Hotovost podle měny",
      emptyMessage: "Snapshot neobsahuje žádnou hotovost podle měny.",
      items,
    })
  )
}

describe("SnapshotCurrencyBreakdown", () => {
  it("renders its heading, currency codes, exact decimals, and server order", () => {
    const output = render(ITEMS)

    expect(output).toContain("<h2")
    expect(output).toContain('aria-labelledby="')
    expect(output).toContain("<dl")
    expect(output).toContain("<dt")
    expect(output).toContain("<dd")
    expect(output).toContain("Hotovost podle měny")
    expect(output).toContain("10 000,000000")
    expect(output).toContain("500,000000")
    expect(output.indexOf("CZK")).toBeLessThan(output.indexOf("EUR"))
    expect(output.indexOf("EUR")).toBeLessThan(output.indexOf("USD"))
  })

  it("keeps negative and zero values visible without classification or filtering", () => {
    const output = render([
      { currency: "EUR", amount: "0.000000" },
      { currency: "USD", amount: "-50.000000" },
    ])

    expect(output).toContain("0,000000")
    expect(output).toContain("-50,000000")
    expect(output).toContain("EUR")
    expect(output).toContain("USD")
  })

  it("renders an explicit empty state without a synthetic currency row", () => {
    const output = render([])

    expect(output).toContain("Snapshot neobsahuje žádnou hotovost podle měny.")
    expect(output).not.toContain("<dl")
    expect(output).not.toContain("<dt")
  })

  it("does not mutate its input or render invalid placeholder values", () => {
    const input = ITEMS.map((item) => ({ ...item }))
    const before = JSON.stringify(input)
    Object.freeze(input)
    for (const item of input) Object.freeze(item)

    const output = render(input)

    expect(JSON.stringify(input)).toBe(before)
    expect(output).not.toMatch(/NaN|undefined|\[object Object\]/)
  })
})
