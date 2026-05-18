import Papa from "papaparse"
import type { ParsedInvestmentTransaction } from "@/types"

export function parseAnycoin(csvText: string, accountId: string): ParsedInvestmentTransaction[] {
  const result = Papa.parse<Record<string, string>>(csvText, {
    header: true,
    skipEmptyLines: true,
  })

  const rows = result.data
  const orders: Record<string, { payment?: Record<string, string>; fill?: Record<string, string> }> = {}
  const standalone: Record<string, string>[] = []

  for (const row of rows) {
    const type = row["Type"]
    const orderId = row["Order ID"]

    if (type === "trade payment" && orderId) {
      if (!orders[orderId]) orders[orderId] = {}
      orders[orderId].payment = row
    } else if (type === "trade fill" && orderId) {
      if (!orders[orderId]) orders[orderId] = {}
      orders[orderId].fill = row
    } else if (type === "trade refund") {
      // zrušený nákup — přeskočit
    } else if (type === "deposit" || type === "withdrawal") {
      standalone.push(row)
    }
  }

  const transactions: ParsedInvestmentTransaction[] = []

  for (const [orderId, order] of Object.entries(orders)) {
    if (!order.payment || !order.fill) continue

    const paidCzk = Math.abs(parseFloat(order.payment["Amount"]))
    const receivedBtc = parseFloat(order.fill["Amount"])
    const avgPriceCzk = paidCzk / receivedBtc

    transactions.push({
      date: new Date(order.fill["Date"]),
      type: "buy",
      symbol: order.fill["Currency"],
      assetType: "crypto",
      quantity: receivedBtc,
      pricePerUnit: avgPriceCzk,
      priceCurrency: order.payment["Currency"],
      totalAmount: paidCzk,
      totalCurrency: "CZK",
      orderId,
      externalId: order.fill["anycoin TX ID"],
      accountId,
    })
  }

  for (const row of standalone) {
    const type = row["Type"]
    if (type === "deposit") {
      transactions.push({
        date: new Date(row["Date"]),
        type: "deposit",
        totalAmount: parseFloat(row["Amount"]),
        totalCurrency: row["Currency"],
        externalId: row["anycoin TX ID"],
        accountId,
      })
    } else if (type === "withdrawal") {
      transactions.push({
        date: new Date(row["Date"]),
        type: "withdrawal",
        quantity: Math.abs(parseFloat(row["Amount"])),
        symbol: row["Currency"],
        externalId: row["anycoin TX ID"],
        accountId,
      })
    }
  }

  return transactions
}
