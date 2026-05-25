import type { CsvRow } from "./csv"

export type ParseIssueSeverity = "ignored" | "warning" | "error"

export interface ParseIssue {
  severity: ParseIssueSeverity
  code: string
  message: string
  rowNumber?: number
  raw?: CsvRow
}

export interface ParseResult<T> {
  rows: T[]
  rowsTotal: number
  issues: ParseIssue[]
}

export interface ParserContext {
  accountId: string
}

export interface RowParseOutcome<T> {
  row: T | null
  issue?: ParseIssue
}

export function createParseResult<T>(
  rows: T[],
  rowsTotal: number,
  issues: ParseIssue[] = []
): ParseResult<T> {
  return { rows, rowsTotal, issues }
}

export function mapParsedRows<T>(
  rawRows: CsvRow[],
  mapRow: (row: CsvRow, rowNumber: number) => RowParseOutcome<T>
): ParseResult<T> {
  const rows: T[] = []
  const issues: ParseIssue[] = []

  rawRows.forEach((rawRow, index) => {
    const rowNumber = index + 1
    const outcome = mapRow(rawRow, rowNumber)

    if (outcome.row) rows.push(outcome.row)
    if (outcome.issue) {
      issues.push({ rowNumber, raw: rawRow, ...outcome.issue })
    }
  })

  return createParseResult(rows, rawRows.length, issues)
}

export function ignoredRow(code: string, message: string): RowParseOutcome<never> {
  return { row: null, issue: { severity: "ignored", code, message } }
}

export function invalidRow(code: string, message: string): RowParseOutcome<never> {
  return { row: null, issue: { severity: "warning", code, message } }
}
