const DECIMAL_STRING = /^([+-]?)(\d+)(?:\.(\d+))?$/

export const UNAVAILABLE_COST_BASIS_LABEL = "Nedostupné – chybí pořizovací cena"

export function formatSnapshotDecimal(value: string | null): string {
  if (value === null) return UNAVAILABLE_COST_BASIS_LABEL
  const match = DECIMAL_STRING.exec(value)
  if (!match) return value

  const [, sign, integer, fraction] = match
  const sourceFraction = fraction ?? ""
  const roundedFraction = sourceFraction.padEnd(2, "0").slice(0, 2)
  const shouldRoundUp = sourceFraction.length > 2 && sourceFraction[2] >= "5"
  const roundedDigits = `${integer}${roundedFraction}`
  const incremented = shouldRoundUp
    ? (BigInt(roundedDigits) + 1n).toString().padStart(3, "0")
    : roundedDigits
  const roundedInteger = incremented.slice(0, -2)
  const groupedInteger = roundedInteger.replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0")
  return `${sign}${groupedInteger},${incremented.slice(-2)}`
}

/** Preserve every decimal place supplied by the snapshot for native-currency evidence. */
export function formatSnapshotExactDecimal(value: string): string {
  const match = DECIMAL_STRING.exec(value)
  if (!match) return value
  const [, sign, integer, fraction] = match
  const groupedInteger = integer.replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0")
  return fraction === undefined ? `${sign}${groupedInteger}` : `${sign}${groupedInteger},${fraction}`
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
