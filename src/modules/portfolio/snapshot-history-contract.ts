import type { components } from "@/generated/python-api"

export type SnapshotPortfolioHistoryResponse = components["schemas"]["PortfolioHistoryResponse"]
export type SnapshotPortfolioHistoryPoint = SnapshotPortfolioHistoryResponse["points"][number]
export type SnapshotPortfolioHistoryRange = SnapshotPortfolioHistoryResponse["range"]
export type SnapshotPortfolioHistoryCoverage = SnapshotPortfolioHistoryResponse["coverage"][number]
export type SnapshotPortfolioHistoryState = SnapshotPortfolioHistoryResponse["state"]

export const SNAPSHOT_PORTFOLIO_HISTORY_RANGES = [
  "1D",
  "1W",
  "1M",
  "3M",
  "6M",
  "1Y",
  "5Y",
  "10Y",
  "ALL",
] as const satisfies readonly SnapshotPortfolioHistoryRange[]

const HISTORY_RANGES = new Set<SnapshotPortfolioHistoryRange>(SNAPSHOT_PORTFOLIO_HISTORY_RANGES)
const HISTORY_STATES = new Set<SnapshotPortfolioHistoryState>([
  "ready",
  "rebuilding",
  "failed",
  "empty",
])
const REQUIRED_RESPONSE_KEYS = [
  "range",
  "state",
  "currency",
  "resolutions",
  "coverage",
  "points",
] as const
const OPTIONAL_RESPONSE_KEYS = [
  "generationId",
  "publicationVersion",
  "coveredThrough",
  "preferredResolutionMinutes",
  "publicationId",
  "valuationTimestamp",
  "isStale",
] as const
const COVERAGE_KEYS = ["resolutionMinutes", "start", "end"] as const
const POINT_KEYS = [
  "timestamp",
  "resolutionMinutes",
  "cashValue",
  "investmentValue",
  "liabilitiesValue",
  "netWorthValue",
] as const
const OPTIONAL_POINT_KEYS = [
  "netInvestedValue",
  "investmentCostBasis",
  "portfolioSnapshotId",
  "realizedPnlValue",
  "unrealizedPnlValue",
  "cashByCurrency",
  "investmentByCurrency",
  "liabilitiesByCurrency",
  "netInvestedByCurrency",
  "positions",
] as const
const MONEY = /^-?(?:0|[1-9]\d{0,11})\.\d{6}$/
const NATIVE_MONEY = /^-?(?:0|[1-9]\d*)\.[0-9]+$|^-?(?:0|[1-9]\d*)$/
const NONNEGATIVE_MONEY = /^(?:0|[1-9]\d{0,11})\.\d{6}$/
const QUANTITY = /^-?(?:0|[1-9]\d{0,17})\.\d{10}$/
const PERCENTAGE = /^(?:0|[1-9]\d{0,2})\.\d{4}$/
const SIGNED_PERCENTAGE = /^-?(?:0|[1-9]\d*)\.\d{4}$/
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}$/
const CURRENCY = /^[A-Z]{3}$/
const MAX_POINTS = 480
const MAX_RESOLUTIONS = 64
const MAX_COVERAGE_SEGMENTS = 480

export class SnapshotPortfolioHistoryContractError extends Error {
  constructor() {
    super("Snapshot portfolio history has an incompatible contract.")
    this.name = "SnapshotPortfolioHistoryContractError"
  }
}

function fail(): never {
  throw new SnapshotPortfolioHistoryContractError()
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function hasResponseKeys(value: Record<string, unknown>): boolean {
  const keys = Object.keys(value)
  const allowed = new Set<string>([...REQUIRED_RESPONSE_KEYS, ...OPTIONAL_RESPONSE_KEYS])
  return (
    REQUIRED_RESPONSE_KEYS.every((key) => Object.hasOwn(value, key)) &&
    keys.every((key) => allowed.has(key))
  )
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const keys = Object.keys(value)
  return keys.length === expected.length && keys.every((key) => expected.includes(key))
}

function isHistoryRange(value: unknown): value is SnapshotPortfolioHistoryRange {
  return typeof value === "string" && HISTORY_RANGES.has(value as SnapshotPortfolioHistoryRange)
}

function isHistoryState(value: unknown): value is SnapshotPortfolioHistoryState {
  return typeof value === "string" && HISTORY_STATES.has(value as SnapshotPortfolioHistoryState)
}

function isResolution(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0
}

function isCanonicalTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || !TIMESTAMP.test(value)) return false
  const date = new Date(`${value}Z`)
  const milliseconds = date.getTime()
  if (milliseconds !== milliseconds) return false
  return date.toISOString() === `${value}Z`
}

function readCoverage(value: unknown): SnapshotPortfolioHistoryCoverage {
  if (!isRecord(value) || !hasExactKeys(value, COVERAGE_KEYS)) fail()
  if (
    !isResolution(value.resolutionMinutes) ||
    !isCanonicalTimestamp(value.start) ||
    !isCanonicalTimestamp(value.end) ||
    value.start >= value.end
  ) {
    fail()
  }
  return {
    resolutionMinutes: value.resolutionMinutes,
    start: value.start,
    end: value.end,
  }
}

function readPoint(value: unknown): SnapshotPortfolioHistoryPoint {
  if (
    !isRecord(value) ||
    !POINT_KEYS.every((key) => Object.hasOwn(value, key)) ||
    !Object.keys(value).every((key) =>
      ([...POINT_KEYS, ...OPTIONAL_POINT_KEYS] as readonly string[]).includes(key)
    )
  )
    fail()
  if (
    !isCanonicalTimestamp(value.timestamp) ||
    !isResolution(value.resolutionMinutes) ||
    typeof value.cashValue !== "string" ||
    !MONEY.test(value.cashValue) ||
    typeof value.investmentValue !== "string" ||
    !NONNEGATIVE_MONEY.test(value.investmentValue) ||
    typeof value.liabilitiesValue !== "string" ||
    !NONNEGATIVE_MONEY.test(value.liabilitiesValue) ||
    typeof value.netWorthValue !== "string" ||
    !MONEY.test(value.netWorthValue) ||
    (value.netInvestedValue !== undefined &&
      (typeof value.netInvestedValue !== "string" || !MONEY.test(value.netInvestedValue))) ||
    (value.investmentCostBasis != null &&
      (typeof value.investmentCostBasis !== "string" ||
        !NONNEGATIVE_MONEY.test(value.investmentCostBasis))) ||
    (value.portfolioSnapshotId !== undefined &&
      (typeof value.portfolioSnapshotId !== "string" ||
        value.portfolioSnapshotId.length === 0 ||
        value.portfolioSnapshotId.trim() !== value.portfolioSnapshotId)) ||
    (value.realizedPnlValue !== undefined &&
      (typeof value.realizedPnlValue !== "string" || !MONEY.test(value.realizedPnlValue))) ||
    (value.unrealizedPnlValue !== undefined &&
      (typeof value.unrealizedPnlValue !== "string" || !MONEY.test(value.unrealizedPnlValue))) ||
    (value.positions !== undefined &&
      value.positions !== null &&
      !Array.isArray(value.positions)) ||
    [
      value.cashByCurrency,
      value.investmentByCurrency,
      value.liabilitiesByCurrency,
      value.netInvestedByCurrency,
    ].some(
      (breakdown) => breakdown !== undefined && breakdown !== null && !Array.isArray(breakdown)
    )
  ) {
    fail()
  }
  return {
    timestamp: value.timestamp,
    resolutionMinutes: value.resolutionMinutes,
    cashValue: value.cashValue,
    investmentValue: value.investmentValue,
    liabilitiesValue: value.liabilitiesValue,
    netWorthValue: value.netWorthValue,
    ...(value.netInvestedValue === undefined ? {} : { netInvestedValue: value.netInvestedValue }),
    ...(value.investmentCostBasis == null
      ? {}
      : { investmentCostBasis: value.investmentCostBasis }),
    ...(value.portfolioSnapshotId === undefined
      ? {}
      : { portfolioSnapshotId: value.portfolioSnapshotId }),
    ...(value.realizedPnlValue === undefined ? {} : { realizedPnlValue: value.realizedPnlValue }),
    ...(value.unrealizedPnlValue === undefined
      ? {}
      : { unrealizedPnlValue: value.unrealizedPnlValue }),
    ...(value.cashByCurrency == null
      ? {}
      : { cashByCurrency: readCurrencyAmounts(value.cashByCurrency) }),
    ...(value.investmentByCurrency == null
      ? {}
      : { investmentByCurrency: readCurrencyAmounts(value.investmentByCurrency) }),
    ...(value.liabilitiesByCurrency == null
      ? {}
      : { liabilitiesByCurrency: readCurrencyAmounts(value.liabilitiesByCurrency) }),
    ...(value.netInvestedByCurrency == null
      ? {}
      : { netInvestedByCurrency: readCurrencyAmounts(value.netInvestedByCurrency) }),
    ...(value.positions == null ? {} : { positions: value.positions.map(readPosition) }),
  }
}

function readCurrencyAmounts(value: unknown) {
  if (!Array.isArray(value)) fail()
  const seen = new Set<string>()
  return value.map((item) => {
    if (
      !isRecord(item) ||
      !hasExactKeys(item, ["currency", "value"]) ||
      typeof item.currency !== "string" ||
      !CURRENCY.test(item.currency) ||
      seen.has(item.currency) ||
      typeof item.value !== "string" ||
      !NATIVE_MONEY.test(item.value)
    )
      fail()
    seen.add(item.currency)
    return { currency: item.currency, value: item.value }
  })
}

function readPositionAccount(value: unknown) {
  const keys = ["accountId", "quantity", "value", "costBasis", "allocationPct"] as const
  if (!isRecord(value) || !Object.keys(value).every((key) => keys.includes(key as never))) fail()
  if (
    typeof value.accountId !== "string" ||
    value.accountId.length === 0 ||
    typeof value.quantity !== "string" ||
    !QUANTITY.test(value.quantity) ||
    typeof value.value !== "string" ||
    !MONEY.test(value.value) ||
    (value.costBasis !== undefined &&
      (typeof value.costBasis !== "string" || !NONNEGATIVE_MONEY.test(value.costBasis))) ||
    typeof value.allocationPct !== "string" ||
    !PERCENTAGE.test(value.allocationPct)
  )
    fail()
  return {
    accountId: value.accountId,
    quantity: value.quantity,
    value: value.value,
    ...(value.costBasis === undefined ? {} : { costBasis: value.costBasis }),
    allocationPct: value.allocationPct,
  }
}

function readPosition(value: unknown) {
  const keys = [
    "listingId",
    "symbol",
    "quantity",
    "value",
    "costBasis",
    "allocationPct",
    "unrealizedPnlPct",
    "accounts",
  ] as const
  if (
    !isRecord(value) ||
    !keys.every(
      (key) => key === "costBasis" || key === "unrealizedPnlPct" || Object.hasOwn(value, key)
    ) ||
    !Object.keys(value).every((key) => keys.includes(key as never))
  )
    fail()
  if (
    typeof value.listingId !== "string" ||
    value.listingId.length === 0 ||
    typeof value.symbol !== "string" ||
    value.symbol.length === 0 ||
    typeof value.quantity !== "string" ||
    !QUANTITY.test(value.quantity) ||
    typeof value.value !== "string" ||
    !MONEY.test(value.value) ||
    (value.costBasis !== undefined &&
      (typeof value.costBasis !== "string" || !NONNEGATIVE_MONEY.test(value.costBasis))) ||
    typeof value.allocationPct !== "string" ||
    !PERCENTAGE.test(value.allocationPct) ||
    (value.unrealizedPnlPct !== undefined &&
      (typeof value.unrealizedPnlPct !== "string" ||
        !SIGNED_PERCENTAGE.test(value.unrealizedPnlPct))) ||
    !Array.isArray(value.accounts)
  )
    fail()
  return {
    listingId: value.listingId,
    symbol: value.symbol,
    quantity: value.quantity,
    value: value.value,
    ...(value.costBasis === undefined ? {} : { costBasis: value.costBasis }),
    allocationPct: value.allocationPct,
    ...(value.unrealizedPnlPct === undefined ? {} : { unrealizedPnlPct: value.unrealizedPnlPct }),
    accounts: value.accounts.map(readPositionAccount),
  }
}

export function parseSnapshotPortfolioHistory(
  value: unknown,
  requestedRange: SnapshotPortfolioHistoryRange,
  expectedCurrency?: string
): SnapshotPortfolioHistoryResponse {
  if (
    !isRecord(value) ||
    !hasResponseKeys(value) ||
    !isHistoryRange(value.range) ||
    value.range !== requestedRange ||
    !isHistoryState(value.state) ||
    typeof value.currency !== "string" ||
    !CURRENCY.test(value.currency) ||
    (expectedCurrency !== undefined && value.currency !== expectedCurrency) ||
    !Array.isArray(value.resolutions) ||
    value.resolutions.length > MAX_RESOLUTIONS ||
    !Array.isArray(value.coverage) ||
    value.coverage.length > MAX_COVERAGE_SEGMENTS ||
    !Array.isArray(value.points) ||
    value.points.length > MAX_POINTS
  ) {
    fail()
  }

  const resolutions = value.resolutions.map((resolution) => {
    if (!isResolution(resolution)) fail()
    return resolution
  })
  if (new Set(resolutions).size !== resolutions.length) {
    fail()
  }

  const coverage: SnapshotPortfolioHistoryCoverage[] = []
  let previousCoverageEnd: string | undefined
  for (const rawCoverage of value.coverage) {
    const segment = readCoverage(rawCoverage)
    if (
      !resolutions.includes(segment.resolutionMinutes) ||
      (previousCoverageEnd !== undefined && segment.start < previousCoverageEnd)
    ) {
      fail()
    }
    coverage.push(segment)
    previousCoverageEnd = segment.end
  }
  const coverageResolutions = new Set(coverage.map((segment) => segment.resolutionMinutes))
  if (
    coverageResolutions.size !== resolutions.length ||
    resolutions.some((resolution) => !coverageResolutions.has(resolution))
  ) {
    fail()
  }

  const points: SnapshotPortfolioHistoryPoint[] = []
  let previousTimestamp: string | undefined
  for (const rawPoint of value.points) {
    const point = readPoint(rawPoint)
    if (
      !resolutions.includes(point.resolutionMinutes) ||
      (previousTimestamp !== undefined && point.timestamp <= previousTimestamp) ||
      !coverage.some(
        (segment) =>
          segment.resolutionMinutes === point.resolutionMinutes &&
          segment.start <= point.timestamp &&
          point.timestamp < segment.end
      )
    ) {
      fail()
    }
    points.push(point)
    previousTimestamp = point.timestamp
  }

  if (
    (value.state === "ready" && points.length === 0) ||
    (value.state === "empty" && points.length !== 0) ||
    (value.state === "empty" && coverage.length !== 0)
  ) {
    fail()
  }

  const generationId = value.generationId
  const publicationVersion = value.publicationVersion
  const coveredThrough = value.coveredThrough
  const preferredResolutionMinutes = value.preferredResolutionMinutes
  const publicationId = value.publicationId
  const valuationTimestamp = value.valuationTimestamp
  const isStale = value.isStale
  const publicationFields = [
    generationId,
    publicationVersion,
    coveredThrough,
    preferredResolutionMinutes,
  ]
  const hasPublication = publicationFields.every((field) => field !== undefined)
  const hasPartialPublication = publicationFields.some((field) => field !== undefined)
  if (
    (generationId !== undefined &&
      (typeof generationId !== "string" ||
        generationId.length > 500 ||
        generationId.trim() !== generationId ||
        generationId.length === 0)) ||
    (publicationVersion !== undefined &&
      (typeof publicationVersion !== "number" ||
        !Number.isSafeInteger(publicationVersion) ||
        publicationVersion < 1)) ||
    (coveredThrough !== undefined &&
      (!isCanonicalTimestamp(coveredThrough) ||
        (previousTimestamp !== undefined && coveredThrough < previousTimestamp))) ||
    (preferredResolutionMinutes !== undefined && !isResolution(preferredResolutionMinutes)) ||
    (publicationId !== undefined &&
      (typeof publicationId !== "string" ||
        publicationId.length === 0 ||
        publicationId.trim() !== publicationId)) ||
    (valuationTimestamp !== undefined && !isCanonicalTimestamp(valuationTimestamp)) ||
    (isStale !== undefined && typeof isStale !== "boolean") ||
    hasPartialPublication !== hasPublication ||
    (hasPublication && resolutions.length === 0) ||
    (!hasPublication &&
      (resolutions.length !== 0 || coverage.length !== 0 || points.length !== 0)) ||
    (value.state === "ready" && !hasPublication) ||
    (value.state === "empty" && hasPublication)
  ) {
    fail()
  }

  return {
    range: value.range,
    state: value.state,
    currency: value.currency,
    ...(generationId === undefined ? {} : { generationId }),
    ...(publicationVersion === undefined ? {} : { publicationVersion }),
    ...(coveredThrough === undefined ? {} : { coveredThrough }),
    ...(preferredResolutionMinutes === undefined ? {} : { preferredResolutionMinutes }),
    ...(publicationId === undefined ? {} : { publicationId }),
    ...(valuationTimestamp === undefined ? {} : { valuationTimestamp }),
    ...(isStale === undefined ? {} : { isStale }),
    resolutions,
    coverage,
    points,
  }
}
