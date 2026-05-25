import Papa from "papaparse"
import type { TransactionType } from "@prisma/client"
import type { CsvRow } from "../shared/csv"

export function cleanValue(value: unknown): string {
  return String(value ?? "")
    .trim()
    .replace(/^"|"$/g, "")
}

function normalizeRow(row: Record<string, unknown>): CsvRow {
  const normalized: CsvRow = {}
  for (const [key, value] of Object.entries(row)) {
    normalized[key.replace(/^﻿/, "").trim()] = cleanValue(value)
  }
  return normalized
}

function isEmptyRow(row: CsvRow): boolean {
  return Object.values(row).every((v) => !v || v.trim() === "")
}

export function parseBankCsvRows(csvText: string): CsvRow[] {
  const result = Papa.parse<Record<string, unknown>>(csvText, {
    delimiter: ";",
    header: true,
    skipEmptyLines: "greedy",
  })
  if (result.errors.length > 0) {
    console.warn("Bank CSV parse warnings:", result.errors)
  }
  return result.data.map(normalizeRow).filter((row) => !isEmptyRow(row))
}

export function buildDescription(parts: Array<string | undefined>): string {
  return parts
    .map(cleanValue)
    .filter(Boolean)
    .filter((v, i, arr) => arr.indexOf(v) === i)
    .join(" | ")
}

export function buildFallbackRef(prefix: string, row: CsvRow, rowIndex: number): string {
  return [
    prefix,
    String(rowIndex),
    row["Datum provedení"] || row["Datum transakce"],
    row["Datum zaúčtování"] || row["Datum zúčtování"],
    row["Zaúčtovaná částka"],
    row["Měna účtu"] || row["Měna zaúčtování"],
    row["Typ transakce"],
    row["Název protiúčtu"] || row["Název Obchodníka"],
    row["Zpráva"] || row["Popis/Místo transakce"],
  ]
    .map(cleanValue)
    .join(":")
    .replace(/\s+/g, " ")
}

export function detectTransactionType(amount: number, transactionText: string): TransactionType {
  const lower = transactionText.toLowerCase()
  if (amount > 0) return "income"
  if (lower.includes("příchozí") || lower.includes("vrácení") || lower.includes("refund"))
    return "income"
  return "expense"
}
