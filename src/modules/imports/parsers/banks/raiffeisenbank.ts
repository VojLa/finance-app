import Papa from "papaparse"
import type { TransactionType } from "@prisma/client"

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

function cleanValue(value: unknown): string {
  return String(value ?? "")
    .trim()
    .replace(/^"|"$/g, "")
}

function normalizeRow(row: Record<string, unknown>): Record<string, string> {
  const normalized: Record<string, string> = {}
  for (const [key, value] of Object.entries(row)) {
    const cleanKey = key.replace(/^﻿/, "").trim()
    normalized[cleanKey] = cleanValue(value)
  }
  return normalized
}

function isEmptyRow(row: Record<string, string>): boolean {
  return Object.values(row).every(value => !value || value.trim() === "")
}

function parseDate(value: unknown): Date | null {
  const str = cleanValue(value)
  if (!str) return null

  const match = str.match(
    /^(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})(?:\s+(\d{1,2}):(\d{2}))?$/
  )
  if (!match) return null

  const [, d, m, y, hh = "0", mm = "0"] = match
  const day = Number(d), month = Number(m), year = Number(y)
  const hour = Number(hh), minute = Number(mm)

  if (
    isNaN(day) || isNaN(month) || isNaN(year) || isNaN(hour) || isNaN(minute) ||
    day < 1 || day > 31 || month < 1 || month > 12 ||
    hour < 0 || hour > 23 || minute < 0 || minute > 59
  ) return null

  return new Date(Date.UTC(year, month - 1, day, hour, minute))
}

function parseAmount(value: unknown): number | null {
  const str = cleanValue(value)
  if (!str) return null
  const normalized = str.replace(/\s/g, "").replace(/ /g, "").replace(",", ".")
  const amount = Number.parseFloat(normalized)
  return Number.isNaN(amount) ? null : amount
}

function detectTransactionType(amount: number, transactionText: string): TransactionType {
  const lower = transactionText.toLowerCase()
  if (amount > 0) return "income"
  if (lower.includes("příchozí") || lower.includes("vrácení") || lower.includes("refund")) return "income"
  return "expense"
}

function buildDescription(parts: Array<string | undefined>): string {
  return parts
    .map(part => cleanValue(part))
    .filter(Boolean)
    .filter((value, index, array) => array.indexOf(value) === index)
    .join(" | ")
}

function buildFallbackRef(prefix: string, row: Record<string, string>, rowIndex: number): string {
  const parts = [
    prefix, String(rowIndex),
    row["Datum provedení"] || row["Datum transakce"],
    row["Datum zaúčtování"] || row["Datum zúčtování"],
    row["Zaúčtovaná částka"],
    row["Měna účtu"] || row["Měna zaúčtování"],
    row["Typ transakce"],
    row["Název protiúčtu"] || row["Název Obchodníka"],
    row["Zpráva"] || row["Popis/Místo transakce"],
  ]
  return parts.map(part => cleanValue(part)).join(":").replace(/\s+/g, " ")
}

function parseAccountStatementRow(row: Record<string, string>, accountId: string, rowIndex: number): RaiffeisenRow | null {
  const amount = parseAmount(row["Zaúčtovaná částka"])
  const date = parseDate(row["Datum provedení"])
  if (amount === null || date === null) return null

  const transactionText = row["Typ transakce"] || ""
  const type = detectTransactionType(amount, transactionText)
  const description = buildDescription([row["Zpráva"], row["Poznámka"], row["Vlastní poznámka"]])

  return {
    date,
    amount: Math.abs(amount),
    currency: row["Měna účtu"] || "CZK",
    type,
    description,
    counterparty: row["Název protiúčtu"] || "",
    transactionRef: row["Id transakce"] || buildFallbackRef("rb-account", row, rowIndex),
    accountId,
  }
}

function parseCardStatementRow(row: Record<string, string>, accountId: string, rowIndex: number): RaiffeisenRow | null {
  const amount = parseAmount(row["Zaúčtovaná částka"])
  const date = parseDate(row["Datum transakce"])
  if (amount === null || date === null) return null

  const transactionText = row["Typ transakce"] || ""
  const type = detectTransactionType(amount, transactionText)
  const merchant = row["Název Obchodníka"] || ""
  const place = row["Popis/Místo transakce"] || ""
  const city = row["Město"] || ""
  const description = buildDescription([place, merchant, city, row["Vlastní poznámka"], transactionText])

  return {
    date,
    amount: Math.abs(amount),
    currency: row["Měna zaúčtování"] || "CZK",
    type,
    description,
    counterparty: merchant || place,
    transactionRef: buildFallbackRef("rb-card", row, rowIndex),
    accountId,
  }
}

function isCardStatement(row: Record<string, string>): boolean {
  return "Číslo kreditní karty" in row || "Datum transakce" in row ||
    "Měna zaúčtování" in row || "Název Obchodníka" in row
}

function isAccountStatement(row: Record<string, string>): boolean {
  return "Datum provedení" in row || "Měna účtu" in row ||
    "Id transakce" in row || "Název protiúčtu" in row
}

export function parseRaiffeisenbank(csvText: string, accountId: string): RaiffeisenRow[] {
  const result = Papa.parse<Record<string, unknown>>(csvText, {
    delimiter: ";",
    header: true,
    skipEmptyLines: "greedy",
  })

  if (result.errors.length > 0) {
    console.warn("Raiffeisenbank CSV parse warnings:", result.errors)
  }

  const parsedRows: RaiffeisenRow[] = []

  result.data.forEach((rawRow, rowIndex) => {
    const row = normalizeRow(rawRow)
    if (isEmptyRow(row)) return

    let parsed: RaiffeisenRow | null = null
    if (isCardStatement(row)) {
      parsed = parseCardStatementRow(row, accountId, rowIndex)
    } else if (isAccountStatement(row)) {
      parsed = parseAccountStatementRow(row, accountId, rowIndex)
    } else {
      console.warn("Unknown Raiffeisenbank row format:", row)
      return
    }

    if (!parsed) {
      console.warn("Skipping invalid Raiffeisenbank row:", row)
      return
    }

    parsedRows.push(parsed)
  })

  return parsedRows
}
