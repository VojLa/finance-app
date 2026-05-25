export function startOfUtcDay(date: Date): Date {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()))
}

export function truncateToMinute(date: Date): Date {
  const next = new Date(date)
  next.setSeconds(0, 0)
  return next
}
