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

function count(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
}

function validateCurrent(value: Record<string, unknown>): CurrentValueSummary {
  if (
    !text(value.asOf) ||
    !text(value.baselineTimestamp) ||
    !text(value.historyAnchorSnapshotId) ||
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

function validateSummary(value: unknown, positionCount: number): void {
  if (!isRecord(value) || value.positionCount !== positionCount) throw contractError()
  for (const field of [
    "cashValue",
    "investmentValue",
    "investmentCostBasis",
    "liabilitiesValue",
    "totalValue",
    "netDepositsValue",
    "realizedPnlValue",
    "unrealizedPnlValue",
    "feesValue",
    "taxesValue",
  ]) {
    if (!decimal(value[field], MONEY)) throw contractError()
  }
  validateCurrencyAmounts(value.cashByCurrency)
  validateCurrencyAmounts(value.netDepositsByCurrency)
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
    !decimal(value.costBasis, QUANTITY) ||
    value.costCurrency !== outputCurrency ||
    !decimal(value.unrealizedPnl, QUANTITY) ||
    !decimal(value.allocationPct, PERCENTAGE) ||
    !decimal(value.nativeValue, QUANTITY) ||
    !currency(value.nativeValueCurrency) ||
    !decimal(value.nativeCostBasis, QUANTITY) ||
    !currency(value.nativeCostCurrency)
  ) {
    throw contractError()
  }
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
    for (const field of [
      "totalValue",
      "cashValue",
      "investmentValue",
      "liabilitiesValue",
      "netDepositsValue",
      "unrealizedPnlValue",
    ]) {
      if (!decimal(account[field], MONEY)) throw contractError()
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
    "investmentCostBasis",
    "netDepositsValue",
    "realizedPnlValue",
    "unrealizedPnlValue",
    "feesValue",
    "taxesValue",
  ]) {
    if (!decimal(value.summary[field], MONEY)) throw contractError()
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
      !decimal(position.unrealizedPnl, QUANTITY) ||
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
  const data = validatePortfolio(await api.readCurrentPortfolio())
  return { status: "ready", current: validateCurrent(data), data }
}

export async function runDashboardSnapshotWorkflow(
  identity: ServerIdentity,
  api: PythonSnapshotApi = createPythonSnapshotApi(identity)
): Promise<SnapshotWorkflowResult<DashboardSnapshotData>> {
  const data = validateDashboard(await api.readCurrentDashboard())
  return { status: "ready", current: validateCurrent(data), data }
}
