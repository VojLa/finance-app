import "server-only"

import type {
  CurrentValueSummary,
  DashboardSnapshotData,
  PortfolioSnapshotData,
  SnapshotWorkflowResult,
} from "../snapshot-workflow-contract"
import { createPythonSnapshotApi, type PythonSnapshotApi } from "./client"
import { contractError } from "./errors"
import type { ServerIdentity } from "./internal-token"

const CURRENCY = /^[A-Z]{3}$/
const MONEY = /^-?(?:0|[1-9]\d{0,11})\.\d{6}$/
const QUANTITY = /^-?(?:0|[1-9]\d{0,17})\.\d{10}$/
const PERCENTAGE = /^(?:0|[1-9]\d{0,3})\.\d{4}$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function text(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value === value.trim()
}

function currency(value: unknown): value is string {
  return typeof value === "string" && CURRENCY.test(value)
}

function decimal(value: unknown, pattern: RegExp): value is string {
  return typeof value === "string" && pattern.test(value)
}

function nullableDecimal(value: unknown, pattern: RegExp): value is string | null {
  return value === null || decimal(value, pattern)
}

function count(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
}

function validateCurrent(value: Record<string, unknown>): CurrentValueSummary {
  if (
    !text(value.asOf) ||
    !text(value.baselineTimestamp) ||
    !text(value.historyAnchorSnapshotId) ||
    !text(value.valuationTimestamp) ||
    typeof value.isStale !== "boolean" ||
    !currency(value.currency) ||
    !count(value.calculationVersion) ||
    value.calculationVersion === 0
  ) {
    throw contractError()
  }
  return {
    asOf: value.asOf,
    baselineTimestamp: value.baselineTimestamp,
    historyAnchorSnapshotId: value.historyAnchorSnapshotId,
    currency: value.currency,
    calculationVersion: value.calculationVersion,
    valuationTimestamp: value.valuationTimestamp,
    isStale: value.isStale,
  }
}

function validateCurrencyAmounts(value: unknown): void {
  if (!Array.isArray(value)) throw contractError()
  const seen = new Set<string>()
  for (const item of value) {
    if (
      !isRecord(item) ||
      !currency(item.currency) ||
      !decimal(item.amount, MONEY) ||
      seen.has(item.currency)
    ) {
      throw contractError()
    }
    seen.add(item.currency)
  }
}

function validatePositiveQuantityCurrencyAmounts(value: unknown): void {
  if (!Array.isArray(value) || value.length === 0) throw contractError()
  let previousCurrency: string | undefined
  for (const item of value) {
    if (
      !isRecord(item) ||
      !currency(item.currency) ||
      !decimal(item.amount, QUANTITY) ||
      item.amount.startsWith("-") ||
      item.amount === "0.0000000000" ||
      (previousCurrency !== undefined && item.currency <= previousCurrency)
    ) {
      throw contractError()
    }
    previousCurrency = item.currency
  }
}

function validateNullableSummaryBranch(value: Record<string, unknown>): void {
  const fields = [
    value.investmentCostBasis,
    value.netDepositsValue,
    value.realizedPnlValue,
    value.unrealizedPnlValue,
    value.netDepositsByCurrency,
  ]
  const incomplete = fields.every((field) => field === null)
  if (incomplete) return
  if (fields.some((field) => field === null)) throw contractError()

  for (const field of fields.slice(0, 4)) {
    if (!decimal(field, MONEY)) throw contractError()
  }
  validateCurrencyAmounts(value.netDepositsByCurrency)
}

function validateSummary(value: unknown, positionCount: number): void {
  if (!isRecord(value) || value.positionCount !== positionCount) throw contractError()
  for (const field of [
    "cashValue",
    "investmentValue",
    "liabilitiesValue",
    "totalValue",
    "feesValue",
    "taxesValue",
  ]) {
    if (!decimal(value[field], MONEY)) throw contractError()
  }
  validateCurrencyAmounts(value.cashByCurrency)
  validateNullableSummaryBranch(value)
}

function validatePosition(value: unknown, outputCurrency: string): void {
  if (
    !isRecord(value) ||
    !text(value.listingId) ||
    !text(value.assetId) ||
    !text(value.symbol) ||
    !text(value.name) ||
    !decimal(value.quantity, QUANTITY) ||
    !decimal(value.pricePerUnit, QUANTITY) ||
    !currency(value.priceCurrency) ||
    !text(value.priceTimestamp) ||
    !decimal(value.value, MONEY) ||
    value.valueCurrency !== outputCurrency ||
    !decimal(value.allocationPct, PERCENTAGE) ||
    !decimal(value.nativeValue, QUANTITY) ||
    !currency(value.nativeValueCurrency)
  ) {
    throw contractError()
  }

  const costFields = [
    value.costBasis,
    value.costCurrency,
    value.unrealizedPnl,
    value.nativeCostBasis,
    value.nativeCostCurrency,
    value.nativeCostBasisByCurrency,
  ]
  const incomplete = costFields.every((field) => field === null)
  if (incomplete) return
  if (
    costFields.some((field) => field === null) ||
    !decimal(value.costBasis, QUANTITY) ||
    value.costCurrency !== outputCurrency ||
    !decimal(value.unrealizedPnl, QUANTITY) ||
    !decimal(value.nativeCostBasis, QUANTITY) ||
    !currency(value.nativeCostCurrency)
  ) {
    throw contractError()
  }
  validatePositiveQuantityCurrencyAmounts(value.nativeCostBasisByCurrency)
}

function validatePortfolio(value: unknown): PortfolioSnapshotData {
  if (
    !isRecord(value) ||
    !Array.isArray(value.accounts) ||
    !Array.isArray(value.aggregatePositions) ||
    !currency(value.currency)
  ) {
    throw contractError()
  }
  const current = validateCurrent(value)
  const accountIds = new Set<string>()
  let positions = 0
  for (const account of value.accounts) {
    if (
      !isRecord(account) ||
      !text(account.baselineSnapshotId) ||
      !text(account.primaryBaselineSnapshotId) ||
      !currency(account.currency) ||
      !isRecord(account.account) ||
      !text(account.account.accountId) ||
      account.account.currency !== account.currency ||
      accountIds.has(account.account.accountId) ||
      !Array.isArray(account.positions)
    ) {
      throw contractError()
    }
    accountIds.add(account.account.accountId)
    for (const position of account.positions) validatePosition(position, account.currency)
    validateSummary(account.summary, account.positions.length)
    positions += account.positions.length
  }
  for (const item of value.aggregatePositions) {
    if (
      !isRecord(item) ||
      !text(item.accountId) ||
      !accountIds.has(item.accountId) ||
      !currency(item.accountCurrency)
    ) {
      throw contractError()
    }
    validatePosition(item.position, current.currency)
  }
  if (value.aggregatePositions.length !== positions) throw contractError()
  validateSummary(value.summary, positions)
  return value as PortfolioSnapshotData
}

function validateDashboard(value: unknown): DashboardSnapshotData {
  if (
    !isRecord(value) ||
    !Array.isArray(value.accounts) ||
    !Array.isArray(value.assetTypeAllocations) ||
    !Array.isArray(value.topPositions) ||
    !currency(value.currency)
  ) {
    throw contractError()
  }
  const current = validateCurrent(value)
  const accountIds = new Set<string>()
  for (const account of value.accounts) {
    if (
      !isRecord(account) ||
      !text(account.accountId) ||
      !text(account.baselineSnapshotId) ||
      !text(account.primaryBaselineSnapshotId) ||
      !currency(account.accountCurrency) ||
      account.outputCurrency !== account.accountCurrency ||
      accountIds.has(account.accountId) ||
      !count(account.positionCount)
    ) {
      throw contractError()
    }
    for (const field of ["totalValue", "cashValue", "investmentValue", "liabilitiesValue"]) {
      if (!decimal(account[field], MONEY)) throw contractError()
    }
    if (
      !nullableDecimal(account.netDepositsValue, MONEY) ||
      !nullableDecimal(account.unrealizedPnlValue, MONEY) ||
      (account.netDepositsValue === null) !== (account.unrealizedPnlValue === null)
    ) {
      throw contractError()
    }
    accountIds.add(account.accountId)
  }
  if (!isRecord(value.summary)) throw contractError()
  for (const field of [
    "totalValue",
    "assetsValue",
    "liabilitiesValue",
    "cashValue",
    "investmentValue",
    "feesValue",
    "taxesValue",
  ]) {
    if (!decimal(value.summary[field], MONEY)) throw contractError()
  }
  const dashboardEvidence = [
    value.summary.investmentCostBasis,
    value.summary.netDepositsValue,
    value.summary.realizedPnlValue,
    value.summary.unrealizedPnlValue,
  ]
  if (
    !dashboardEvidence.every((field) => field === null) &&
    (dashboardEvidence.some((field) => field === null) ||
      dashboardEvidence.some((field) => !decimal(field, MONEY)))
  ) {
    throw contractError()
  }
  for (const field of [
    "accountCount",
    "investmentAccountCount",
    "liabilityAccountCount",
    "positionCount",
  ]) {
    if (!count(value.summary[field])) throw contractError()
  }
  for (const allocation of value.assetTypeAllocations) {
    if (
      !isRecord(allocation) ||
      !decimal(allocation.value, MONEY) ||
      !decimal(allocation.allocationPct, PERCENTAGE) ||
      !count(allocation.accountCount) ||
      !count(allocation.positionCount)
    ) {
      throw contractError()
    }
  }
  for (const position of value.topPositions) {
    if (
      !isRecord(position) ||
      !accountIds.has(String(position.accountId)) ||
      !decimal(position.value, MONEY) ||
      position.valueCurrency !== current.currency ||
      !nullableDecimal(position.unrealizedPnl, QUANTITY) ||
      !decimal(position.allocationPct, PERCENTAGE)
    ) {
      throw contractError()
    }
  }
  return value as DashboardSnapshotData
}

export async function runPortfolioSnapshotWorkflow(
  identity: ServerIdentity,
  api: PythonSnapshotApi = createPythonSnapshotApi(identity)
): Promise<SnapshotWorkflowResult<PortfolioSnapshotData>> {
  const data = validatePortfolio(await api.readPublishedPortfolio())
  return { status: "ready", current: validateCurrent(data), data }
}

export async function refreshPortfolioSnapshotWorkflow(
  identity: ServerIdentity,
  api: PythonSnapshotApi = createPythonSnapshotApi(identity)
): Promise<SnapshotWorkflowResult<PortfolioSnapshotData>> {
  await api.recalculateSnapshotRefresh()
  return runPortfolioSnapshotWorkflow(identity, api)
}

export async function runDashboardSnapshotWorkflow(
  identity: ServerIdentity,
  api: PythonSnapshotApi = createPythonSnapshotApi(identity)
): Promise<SnapshotWorkflowResult<DashboardSnapshotData>> {
  const data = validateDashboard(await api.readPublishedDashboard())
  return { status: "ready", current: validateCurrent(data), data }
}
