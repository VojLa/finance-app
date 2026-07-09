import Papa from "papaparse"

export type CsvRow = Record<string, string>

export interface ParseCsvRowsOptions {
  delimiter?: string
  skipEmptyLines?: boolean | "greedy"
  cleanValues?: boolean
  normalizeHeaders?: boolean
  dropEmptyRows?: boolean
  warnOnErrors?: boolean
}

export function cleanCsvValue(value: unknown): string {
  return String(value ?? "")
    .trim()
    .replace(/^"|"$/g, "")
}

export function normalizeCsvHeader(header: string): string {
  return header.replace(/^\uFEFF/, "").trim()
}

function isEmptyRow(row: CsvRow): boolean {
  return Object.values(row).every((value) => !value || value.trim() === "")
}

function modifyRows(
  row: Record<string, unknown>,
  options: Required<Pick<ParseCsvRowsOptions, "cleanValues" | "normalizeHeaders">>
): CsvRow {
  const normalized: CsvRow = {}

  for (const [key, value] of Object.entries(row)) {
    const normalizedKey = options.normalizeHeaders ? normalizeCsvHeader(key) : key
    normalized[normalizedKey] = options.cleanValues ? cleanCsvValue(value) : String(value ?? "")
  }

  return normalized
}

export function parseCsvRows(csvText: string, options: ParseCsvRowsOptions = {}): CsvRow[] {
  const {
    delimiter,
    skipEmptyLines = true,
    cleanValues = true,
    normalizeHeaders = true,
    dropEmptyRows = true,
    warnOnErrors = true,
  } = options

  const result = Papa.parse<Record<string, unknown>>(csvText, {
    delimiter,
    header: true,
    skipEmptyLines,
  })

  if (warnOnErrors && result.errors.length > 0) {
    console.warn("CSV parse warnings:", result.errors)
  }

  const rows = result.data.map((row) => modifyRows(row, { cleanValues, normalizeHeaders }))

  return dropEmptyRows ? rows.filter((row) => !isEmptyRow(row)) : rows
}

export function get(row: Record<string, string>, keys: string[]): string | undefined {
  return keys.map((key) => row[key]).find((value) => value && value.trim() !== "")
}

export function normalizeText(value: string | undefined): string {
  return (value || "").trim().toLowerCase()
}
