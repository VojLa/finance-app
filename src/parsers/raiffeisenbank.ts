import Papa from "papaparse"
import type { TransactionType } from "@prisma/client"

const INCOME_KEYWORDS = ["Příchozí úhrada", "Příchozí SEPA úhrada", "Příchozí platba", "Přijatá platba"]
const EXPENSE_KEYWORDS = ["Odchozí úhrada", "Odchozí SEPA úhrada", "Platba kartou", "Výběr z bankomatu"]

function parseDate(str: string): Date {
  // "15.05.2026" nebo "15.05.2026 10:32"
  const [datePart] = str.trim().split(" ")
  const [d, m, y] = datePart.split(".")
  return new Date(`${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`)
}

function parseAmount(str: string): number {
  return parseFloat(str.replace(/\s/g, "").replace(",", "."))
}

export interface RaiffeisenRow {
  date: Date
  amount: number
  currency: string
  type: TransactionType
  description: string
  counterparty: string
  transactionRef: string
  accountId: string
}

export function parseRaiffeisenbank(csvText: string, accountId: string): RaiffeisenRow[] {
  const result = Papa.parse<Record<string, string>>(csvText, {
    delimiter: ";",
    header: true,
    skipEmptyLines: true,
  })

  return result.data
    .map((row): RaiffeisenRow | null => {
      const amountRaw = row["Zaúčtovaná částka"]
      if (!amountRaw) return null

      const amount = parseAmount(amountRaw)
      const typText = row["Typ transakce"] ?? ""

      let type: TransactionType = "expense"
      if (INCOME_KEYWORDS.some(k => typText.includes(k))) type = "income"
      if (amount > 0) type = "income"

      const description = [row["Zpráva"], row["Poznámka"]]
        .filter(Boolean)
        .join(" | ")
        .trim()

      return {
        date: parseDate(row["Datum provedení"] ?? ""),
        amount: Math.abs(amount),
        currency: row["Měna účtu"] ?? "CZK",
        type,
        description,
        counterparty: row["Název protiúčtu"] ?? "",
        transactionRef: row["Id transakce"] ?? "",
        accountId,
      }
    })
    .filter((r): r is RaiffeisenRow => r !== null)
}
