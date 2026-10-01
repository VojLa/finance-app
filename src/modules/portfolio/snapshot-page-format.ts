const DECIMAL_STRING = /^([+-]?)(\d+)(?:\.(\d+))?$/

export const UNAVAILABLE_COST_BASIS_LABEL = "Nedostupné – chybí pořizovací cena"

type RoundedDecimal = Readonly<{
  sign: "" | "-"
  integer: string
  fraction: string
}>

function roundDecimal(value: string, fractionDigits: number): RoundedDecimal | null {
  const match = DECIMAL_STRING.exec(value)
  if (!match) return null
  const [, rawSign, integer, rawFraction] = match
  const fraction = (rawFraction ?? "").padEnd(fractionDigits + 1, "0")
  const retainedFraction = fraction.slice(0, fractionDigits)
  const magnitudeDigits = `${integer}${retainedFraction}`
  const roundedMagnitude =
    fraction[fractionDigits] >= "5"
      ? BigInt(magnitudeDigits || "0") + 1n
      : BigInt(magnitudeDigits || "0")
  const padded = roundedMagnitude.toString().padStart(integer.length + fractionDigits, "0")
  const roundedInteger = fractionDigits === 0 ? padded : padded.slice(0, -fractionDigits)
  const roundedFraction = fractionDigits === 0 ? "" : padded.slice(-fractionDigits)
  const isZero = /^0+$/.test(`${roundedInteger}${roundedFraction}`)
  return {
    sign: rawSign === "-" && !isZero ? "-" : "",
    integer: roundedInteger,
    fraction: roundedFraction,
  }
}

function formatRoundedDecimal(value: string, fractionDigits: number): string {
  const rounded = roundDecimal(value, fractionDigits)
  if (rounded === null) return value
  const groupedInteger = rounded.integer.replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0")
  return fractionDigits === 0
    ? `${rounded.sign}${groupedInteger}`
    : `${rounded.sign}${groupedInteger},${rounded.fraction}`
}

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
  return fraction === undefined
    ? `${sign}${groupedInteger}`
    : `${sign}${groupedInteger},${fraction}`
}

export function formatSnapshotAmount(value: string | null, currency: string | null): string {
  if (value === null || currency === null) return UNAVAILABLE_COST_BASIS_LABEL
  return `${formatSnapshotDecimal(value)} ${currency}`
}

export function formatSnapshotPercentage(value: string): string {
  return formatRoundedDecimal(value, 1)
}

export type SnapshotPercentageTone = "positive" | "negative" | "neutral" | "unavailable"

export function snapshotPercentageTone(value: string | undefined): SnapshotPercentageTone {
  if (value === undefined) return "unavailable"
  const rounded = roundDecimal(value, 1)
  if (rounded === null) return "unavailable"
  if (/^0+$/.test(`${rounded.integer}${rounded.fraction}`)) return "neutral"
  return rounded.sign === "-" ? "negative" : "positive"
}

export function formatSnapshotQuantity(value: string): string {
  const match = DECIMAL_STRING.exec(value)
  if (!match) return value
  const [, , integer, fraction = ""] = match
  if (!/^0+$/.test(integer)) return formatRoundedDecimal(value, 2)

  const firstNonzero = fraction.search(/[1-9]/)
  if (firstNonzero < 0) return formatRoundedDecimal(value, 2)
  const fractionDigits =
    firstNonzero === 0 ? 3 : firstNonzero <= 2 ? 4 : Math.min(fraction.length, firstNonzero + 2)
  return formatRoundedDecimal(value, fractionDigits)
}

export function formatSnapshotTimestamp(value: string): string {
  const hasTimeZone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
  const timestamp = new Date(hasTimeZone ? value : `${value}Z`)
  if (Number.isNaN(timestamp.getTime())) return value
  return timestamp.toLocaleString("cs-CZ", {
    dateStyle: "medium",
    timeStyle: "short",
  })
}
