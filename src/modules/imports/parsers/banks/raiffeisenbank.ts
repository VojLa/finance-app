import type { TransactionType } from "@prisma/client"
import { parseCsvRows, type CsvRow } from "../shared/csv"
import { parseNum } from "../shared/number"
import { parseCzechDate } from "../shared/date"
import { buildDescription, buildFallbackRef, detectTransactionType } from "./shared"
import { mapParsedRows, type ParseResult, type RowParseOutcome } from "../shared/result"

export interface ParsedTransaction {
  date: Date
  amount: number
  currency: string
  type: TransactionType
  description: string
  counterparty: string
  externalId: string
  accountId: string
}

export type RaiffeisenRow = ParsedTransaction

function isCardStatement(row: CsvRow): boolean {
  return (
    "Číslo kreditní karty" in row ||
    "Datum transakce" in row ||
    "Měna zaúčtování" in row ||
    "Název Obchodníka" in row
  )
}

function isAccountStatement(row: CsvRow): boolean {
  return (
    "Datum provedení" in row ||
    "Měna účtu" in row ||
    "Id transakce" in row ||
    "Název protiúčtu" in row
  )
}

function parseAccountRow(
  row: CsvRow,
  accountId: string,
  rowIndex: number
): ParsedTransaction | null {
  const amount = parseNum(row["Zaúčtovaná částka"])
  const date = parseCzechDate(row["Datum provedení"])
  if (amount === null || date === null) return null

  const transactionText = row["Typ transakce"] || ""
  return {
    date,
    amount: Math.abs(amount),
    currency: row["Měna účtu"] || "CZK",
    type: detectTransactionType(amount, transactionText),
    description: buildDescription([row["Zpráva"], row["Poznámka"], row["Vlastní poznámka"]]),
    counterparty: row["Název protiúčtu"] || "",
    externalId: row["Id transakce"] || buildFallbackRef("rb-account", row, rowIndex),
    accountId,
  }
}

function parseCardRow(row: CsvRow, accountId: string, rowIndex: number): ParsedTransaction | null {
  const amount = parseNum(row["Zaúčtovaná částka"])
  const date = parseCzechDate(row["Datum transakce"])
  if (amount === null || date === null) return null

  const transactionText = row["Typ transakce"] || ""
  const merchant = row["Název Obchodníka"] || ""
  const place = row["Popis/Místo transakce"] || ""
  return {
    date,
    amount: Math.abs(amount),
    currency: row["Měna zaúčtování"] || "CZK",
    type: detectTransactionType(amount, transactionText),
    description: buildDescription([
      place,
      merchant,
      row["Město"],
      row["Vlastní poznámka"],
      transactionText,
    ]),
    counterparty: merchant || place,
    externalId: buildFallbackRef("rb-card", row, rowIndex),
    accountId,
  }
}

function parseRow(
  row: CsvRow,
  accountId: string,
  rowIndex: number
): RowParseOutcome<ParsedTransaction> {
  const parsed = isCardStatement(row)
    ? parseCardRow(row, accountId, rowIndex)
    : isAccountStatement(row)
      ? parseAccountRow(row, accountId, rowIndex)
      : null

  if (parsed) return { row: parsed }

  return {
    row: null,
    issue: {
      severity: "warning",
      code: "unsupported_raiffeisenbank_row",
      message: "Unknown or invalid Raiffeisenbank row format.",
    },
  }
}

export function parseRaiffeisenbankResult(
  csvText: string,
  accountId: string
): ParseResult<ParsedTransaction> {
  return mapParsedRows(
    parseCsvRows(csvText, { delimiter: ";", skipEmptyLines: "greedy" }),
    (row, rowNumber) => parseRow(row, accountId, rowNumber - 1)
  )
}

export function parseRaiffeisenbank(csvText: string, accountId: string): ParsedTransaction[] {
  return parseRaiffeisenbankResult(csvText, accountId).rows
}
