export function parseIsoDate(value: string | undefined): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

export function parseCzechDate(value: string | undefined): Date | null {
  if (!value) return null
  const match = value.match(/^(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})(?:\s+(\d{1,2}):(\d{2}))?$/)
  if (!match) return null
  const [, d, m, y, hh = "0", mm = "0"] = match
  const day = Number(d),
    month = Number(m),
    year = Number(y)
  const hour = Number(hh),
    minute = Number(mm)
  if (
    isNaN(day) ||
    isNaN(month) ||
    isNaN(year) ||
    isNaN(hour) ||
    isNaN(minute) ||
    day < 1 ||
    day > 31 ||
    month < 1 ||
    month > 12 ||
    hour < 0 ||
    hour > 23 ||
    minute < 0 ||
    minute > 59
  )
    return null
  return new Date(Date.UTC(year, month - 1, day, hour, minute))
}

export function latestDate(dates: Array<Date | null>): Date | null {
  return dates.reduce<Date | null>((latest, date) => {
    if (!date) return latest
    if (!latest || date > latest) return date
    return latest
  }, null)
}
