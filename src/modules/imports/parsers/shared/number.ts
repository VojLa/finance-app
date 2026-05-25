export function parseNum(value: string | undefined): number | null {
  if (!value || value.trim() === "") return null
  const normalized = value
    .trim()
    .replace(/\s/g, "")
    .replace(/^[(](.*)[)]$/, "-$1")
    .replace(",", ".")
  const n = Number.parseFloat(normalized)
  return Number.isFinite(n) ? n : null
}

export function sumAbsNums(row: Record<string, string>, keys: string[]): number | null {
  const total = keys.reduce((sum, key) => sum + Math.abs(parseNum(row[key]) ?? 0), 0)
  return total > 0 ? total : null
}
