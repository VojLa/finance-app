import type { components } from "@/generated/python-api"

export type SnapshotPortfolioHistoryResponse = components["schemas"]["PortfolioHistoryResponse"]
export type SnapshotPortfolioHistoryPoint = components["schemas"]["PortfolioHistoryPointResponse"]
export type SnapshotPortfolioHistoryRange = components["schemas"]["PortfolioHistoryRange"]

const HISTORY_RANGES = new Set<SnapshotPortfolioHistoryRange>(["1W", "1M", "3M", "6M", "1Y", "ALL"])
const RESPONSE_KEYS = ["range", "currency", "points"] as const
const POINT_KEYS = [
  "timestamp",
  "cashValue",
  "investmentValue",
  "liabilitiesValue",
  "netWorthValue",
] as const
const MONEY = /^-?(?:0|[1-9]\d{0,11})\.\d{6}$/
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}$/
const MAX_POINTS = 512

export class SnapshotPortfolioHistoryContractError extends Error {
  constructor() {
    super("Snapshot portfolio history has an incompatible contract.")
    this.name = "SnapshotPortfolioHistoryContractError"
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const keys = Object.keys(value)
  return keys.length === expected.length && keys.every((key) => expected.includes(key))
}

function isHistoryRange(value: unknown): value is SnapshotPortfolioHistoryRange {
  return typeof value === "string" && HISTORY_RANGES.has(value as SnapshotPortfolioHistoryRange)
}

function isCanonicalTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || !TIMESTAMP.test(value)) return false
  const date = new Date(`${value}Z`)
  const milliseconds = date.getTime()
  if (milliseconds !== milliseconds) return false
  return date.toISOString() === `${value}Z`
}

function readPoint(value: unknown): SnapshotPortfolioHistoryPoint {
  if (!isRecord(value) || !hasExactKeys(value, POINT_KEYS)) {
    throw new SnapshotPortfolioHistoryContractError()
  }
  if (
    !isCanonicalTimestamp(value.timestamp) ||
    typeof value.cashValue !== "string" ||
    !MONEY.test(value.cashValue) ||
    typeof value.investmentValue !== "string" ||
    !MONEY.test(value.investmentValue) ||
    typeof value.liabilitiesValue !== "string" ||
    !MONEY.test(value.liabilitiesValue) ||
    typeof value.netWorthValue !== "string" ||
    !MONEY.test(value.netWorthValue)
  ) {
    throw new SnapshotPortfolioHistoryContractError()
  }
  return {
    timestamp: value.timestamp,
    cashValue: value.cashValue,
    investmentValue: value.investmentValue,
    liabilitiesValue: value.liabilitiesValue,
    netWorthValue: value.netWorthValue,
  }
}

export function parseSnapshotPortfolioHistory(
  value: unknown,
  requestedRange: SnapshotPortfolioHistoryRange,
  expectedCurrency?: string
): SnapshotPortfolioHistoryResponse {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, RESPONSE_KEYS) ||
    !isHistoryRange(value.range) ||
    value.range !== requestedRange ||
    typeof value.currency !== "string" ||
    !/^[A-Z]{3}$/.test(value.currency) ||
    (expectedCurrency !== undefined && value.currency !== expectedCurrency) ||
    !Array.isArray(value.points) ||
    value.points.length > MAX_POINTS
  ) {
    throw new SnapshotPortfolioHistoryContractError()
  }

  const points: SnapshotPortfolioHistoryPoint[] = []
  let previousTimestamp: string | undefined
  for (const rawPoint of value.points) {
    const point = readPoint(rawPoint)
    if (previousTimestamp !== undefined && point.timestamp <= previousTimestamp) {
      throw new SnapshotPortfolioHistoryContractError()
    }
    points.push(point)
    previousTimestamp = point.timestamp
  }

  return {
    range: value.range,
    currency: value.currency,
    points,
  }
}
