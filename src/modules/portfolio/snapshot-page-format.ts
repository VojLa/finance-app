const DECIMAL_STRING = /^([+-]?)(\d+)(?:\.(\d+))?$/

export const UNAVAILABLE_COST_BASIS_LABEL = "Nedostupné – chybí pořizovací cena"

export function formatSnapshotDecimal(value: string | null): string {
  if (value === null) return UNAVAILABLE_COST_BASIS_LABEL
  const match = DECIMAL_STRING.exec(value)
  if (!match) return value

  const [, sign, integer, fraction] = match
  const groupedInteger = integer.replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0")
  return `${sign}${groupedInteger}${fraction === undefined ? "" : `,${fraction}`}`
}

export function formatSnapshotAmount(value: string | null, currency: string | null): string {
  if (value === null || currency === null) return UNAVAILABLE_COST_BASIS_LABEL
  return `${formatSnapshotDecimal(value)} ${currency}`
}

export function formatSnapshotTimestamp(value: string): string {
  const timestamp = new Date(value)
  if (Number.isNaN(timestamp.getTime())) return value
  return timestamp.toLocaleString("cs-CZ", {
    dateStyle: "medium",
    timeStyle: "short",
  })
}
