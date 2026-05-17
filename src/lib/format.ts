export function fmt(n: number | null | undefined, decimals = 2): string {
  if (n === null || n === undefined) return "—"
  return n.toLocaleString("cs-CZ", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

export function fmtCzk(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—"
  return n.toLocaleString("cs-CZ", { minimumFractionDigits: 0, maximumFractionDigits: 0 }) + " Kč"
}

export function fmtPct(n: number): string {
  return (n >= 0 ? "+" : "") + n.toLocaleString("cs-CZ", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " %"
}
