import Papa from "papaparse"

export type CsvRow = Record<string, string>

export function parseCsvRows(csvText: string): CsvRow[] {
  return Papa.parse<CsvRow>(csvText, {
    header: true,
    skipEmptyLines: true,
  }).data
}

export function get(row: Record<string, string>, keys: string[]): string | undefined {
  return keys.map((key) => row[key]).find((value) => value && value.trim() !== "")
}

export function normalizeText(value: string | undefined): string {
  return (value || "").trim().toLowerCase()
}
