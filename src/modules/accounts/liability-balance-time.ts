export function defaultLiabilityEffectiveAt(now = new Date()): string {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 19)
}

export function toNaiveUtcLiabilityTimestamp(localValue: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$/.test(localValue)) {
    throw new TypeError("Invalid local liability timestamp.")
  }
  const value = new Date(localValue)
  if (Number.isNaN(value.getTime())) {
    throw new TypeError("Invalid local liability timestamp.")
  }
  return value.toISOString().slice(0, -1)
}
