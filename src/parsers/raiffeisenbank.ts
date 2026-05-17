import Papa from "papaparse"

export function parseRaiffeisenbank(csvText: string) {
  return Papa.parse(csvText, {
    delimiter: ";",
    header: true,
    skipEmptyLines: true,
  })
}
