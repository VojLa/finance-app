import type { TransactionType } from "@prisma/client"
import { cleanCsvValue, type CsvRow } from "../shared/csv"

export function buildDescription(parts: Array<string | undefined>): string {
  return parts
    .map(cleanCsvValue)
    .filter(Boolean)
    .filter((value, index, values) => values.indexOf(value) === index)
    .join(" | ")
}

export function buildFallbackRef(prefix: string, row: CsvRow, rowIndex: number): string {
  return [
    prefix,
    String(rowIndex),
    row["Datum provedenĂ­"] || row["Datum transakce"],
    row["Datum zaĂşÄŤtovĂˇnĂ­"] || row["Datum zĂşÄŤtovĂˇnĂ­"],
    row["ZaĂşÄŤtovanĂˇ ÄŤĂˇstka"],
    row["MÄ›na ĂşÄŤtu"] || row["MÄ›na zaĂşÄŤtovĂˇnĂ­"],
    row["Typ transakce"],
    row["NĂˇzev protiĂşÄŤtu"] || row["NĂˇzev ObchodnĂ­ka"],
    row["ZprĂˇva"] || row["Popis/MĂ­sto transakce"],
  ]
    .map(cleanCsvValue)
    .join(":")
    .replace(/\s+/g, " ")
}

export function detectTransactionType(amount: number, transactionText: string): TransactionType {
  const lower = transactionText.toLowerCase()
  if (amount > 0) return "income"
  if (lower.includes("pĹ™Ă­chozĂ­") || lower.includes("vrĂˇcenĂ­") || lower.includes("refund")) {
    return "income"
  }
  return "expense"
}
