const DECIMAL_STRING = /^([+-]?)(\d+)(?:\.(\d+))?$/

export function formatSnapshotDecimal(value: string): string {
  const match = DECIMAL_STRING.exec(value)
  if (!match) return value

  const [, sign, integer, fraction] = match
  const groupedInteger = integer.replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0")
  return `${sign}${groupedInteger}${fraction === undefined ? "" : `,${fraction}`}`
}

export function formatSnapshotAmount(value: string, currency: string): string {
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
