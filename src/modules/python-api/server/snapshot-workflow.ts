import "server-only"

import type {
  DashboardSnapshotData,
  ExactPortfolioSnapshotManifest,
  PortfolioSnapshotData,
  PythonSnapshotRefreshResponse,
  SnapshotRefreshSummary,
  SnapshotWorkflowResult,
} from "../snapshot-workflow-contract"
import { createPythonSnapshotApi, type PythonSnapshotApi } from "./client"
import { contractError } from "./errors"
import type { ServerIdentity } from "./internal-token"

type WorkflowKind = "portfolio" | "dashboard"

type ValidatedRefresh = {
  response: PythonSnapshotRefreshResponse
  summary: SnapshotRefreshSummary
  manifest: ExactPortfolioSnapshotManifest | null
}

const CURRENCY = /^[A-Z]{3}$/
const MONEY = /^-?(?:0|[1-9]\d{0,11})\.\d{6}$/
const QUANTITY = /^-?(?:0|[1-9]\d{0,17})\.\d{10}$/
const PERCENTAGE = /^(?:0|[1-9]\d{0,3})\.\d{4}$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function nonBlankString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0
}

function trimmedNonBlankString(value: unknown): value is string {
  return nonBlankString(value) && value === value.trim()
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
}

function positiveInteger(value: unknown): value is number {
  return nonNegativeInteger(value) && value > 0
}

function currency(value: unknown): value is string {
  return typeof value === "string" && CURRENCY.test(value)
}

function exactDecimal(value: unknown, pattern: RegExp): value is string {
  return typeof value === "string" && pattern.test(value)
}

function validateCurrencyAmounts(value: unknown): void {
  if (!Array.isArray(value)) {
    throw contractError()
  }
  const currencies = new Set<string>()
  for (const item of value) {
    if (
      !isRecord(item) ||
      !currency(item.currency) ||
      !exactDecimal(item.amount, MONEY) ||
      currencies.has(item.currency)
    ) {
      throw contractError()
    }
    currencies.add(item.currency)
  }
}

function validatePortfolioSummary(value: unknown, positionCount: number): void {
  if (!isRecord(value) || value.positionCount !== positionCount) {
    throw contractError()
  }
  const moneyFields = [
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
  ] as const
  if (moneyFields.some((field) => !exactDecimal(value[field], MONEY))) {
    throw contractError()
  }
  validateCurrencyAmounts(value.cashByCurrency)
  validateCurrencyAmounts(value.netDepositsByCurrency)
}

function validatePortfolioPosition(value: unknown, outputCurrency: string): void {
  if (
    !isRecord(value) ||
    !trimmedNonBlankString(value.listingId) ||
    !trimmedNonBlankString(value.assetId) ||
    !trimmedNonBlankString(value.symbol) ||
    !trimmedNonBlankString(value.name) ||
    !exactDecimal(value.quantity, QUANTITY) ||
    !exactDecimal(value.pricePerUnit, QUANTITY) ||
    !currency(value.priceCurrency) ||
    !trimmedNonBlankString(value.priceTimestamp) ||
    !exactDecimal(value.value, MONEY) ||
    value.valueCurrency !== outputCurrency ||
    !exactDecimal(value.costBasis, QUANTITY) ||
    value.costCurrency !== outputCurrency ||
    !exactDecimal(value.unrealizedPnl, QUANTITY) ||
    !exactDecimal(value.allocationPct, PERCENTAGE) ||
    !exactDecimal(value.nativeValue, QUANTITY) ||
    !currency(value.nativeValueCurrency) ||
    !exactDecimal(value.nativeCostBasis, QUANTITY) ||
    !currency(value.nativeCostCurrency)
  ) {
    throw contractError()
  }
}

function validateDashboardSummary(value: unknown): void {
  if (!isRecord(value)) {
    throw contractError()
  }
  const moneyFields = [
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
  ] as const
  const countFields = [
    "accountCount",
    "investmentAccountCount",
    "liabilityAccountCount",
    "positionCount",
  ] as const
  if (
    moneyFields.some((field) => !exactDecimal(value[field], MONEY)) ||
    countFields.some((field) => !nonNegativeInteger(value[field]))
  ) {
    throw contractError()
  }
}

function validateRefresh(value: unknown): ValidatedRefresh {
  if (!isRecord(value) || !Array.isArray(value.accounts)) {
    throw contractError()
  }
  if (
    !nonBlankString(value.netWorthSnapshotId) ||
    (value.netWorthStatus !== "created" && value.netWorthStatus !== "replayed") ||
    !nonBlankString(value.timestamp) ||
    !nonBlankString(value.granularity) ||
    typeof value.currency !== "string" ||
    !/^[A-Z]{3}$/.test(value.currency) ||
    !positiveInteger(value.calculationVersion)
  ) {
    throw contractError()
  }

  const countFields = [
    "refreshAccountCount",
    "reuseOnlyAccountCount",
    "createdAccountSnapshotCount",
    "replayedAccountSnapshotCount",
    "reusedAccountSnapshotCount",
    "selectedAccountSnapshotCount",
  ] as const
  if (countFields.some((field) => !nonNegativeInteger(value[field]))) {
    throw contractError()
  }

  const refreshAccountCount = value.refreshAccountCount as number
  const reuseOnlyAccountCount = value.reuseOnlyAccountCount as number
  const createdAccountSnapshotCount = value.createdAccountSnapshotCount as number
  const replayedAccountSnapshotCount = value.replayedAccountSnapshotCount as number
  const reusedAccountSnapshotCount = value.reusedAccountSnapshotCount as number
  const selectedAccountSnapshotCount = value.selectedAccountSnapshotCount as number

  if (
    selectedAccountSnapshotCount !== value.accounts.length ||
    refreshAccountCount !== createdAccountSnapshotCount + replayedAccountSnapshotCount ||
    reuseOnlyAccountCount !== reusedAccountSnapshotCount ||
    selectedAccountSnapshotCount !== refreshAccountCount + reuseOnlyAccountCount
  ) {
    throw contractError()
  }

  const response = value as PythonSnapshotRefreshResponse
  const summary: SnapshotRefreshSummary = {
    netWorthSnapshotId: response.netWorthSnapshotId,
    netWorthStatus: response.netWorthStatus,
    timestamp: response.timestamp,
    granularity: response.granularity,
    currency: response.currency,
    calculationVersion: response.calculationVersion,
    refreshAccountCount: response.refreshAccountCount,
    reuseOnlyAccountCount: response.reuseOnlyAccountCount,
    createdAccountSnapshotCount: response.createdAccountSnapshotCount,
    replayedAccountSnapshotCount: response.replayedAccountSnapshotCount,
    reusedAccountSnapshotCount: response.reusedAccountSnapshotCount,
    selectedAccountSnapshotCount: response.selectedAccountSnapshotCount,
  }

  if (response.accounts.length === 0) {
    if (
      refreshAccountCount !== 0 ||
      reuseOnlyAccountCount !== 0 ||
      createdAccountSnapshotCount !== 0 ||
      replayedAccountSnapshotCount !== 0 ||
      reusedAccountSnapshotCount !== 0 ||
      selectedAccountSnapshotCount !== 0
    ) {
      throw contractError()
    }
    return { response, summary, manifest: null }
  }

  const accountIds = new Set<string>()
  const snapshotIds = new Set<string>()
  for (const item of response.accounts) {
    if (
      !isRecord(item) ||
      !trimmedNonBlankString(item.accountId) ||
      !trimmedNonBlankString(item.snapshotId) ||
      accountIds.has(item.accountId) ||
      snapshotIds.has(item.snapshotId)
    ) {
      throw contractError()
    }
    accountIds.add(item.accountId)
    snapshotIds.add(item.snapshotId)
  }

  return {
    response,
    summary,
    manifest: {
      timestamp: response.timestamp,
      granularity: response.granularity,
      currency: response.currency,
      calculationVersion: response.calculationVersion,
      accounts: response.accounts,
    },
  }
}

function validateCommonIdentity(
  value: unknown,
  manifest: ExactPortfolioSnapshotManifest
): asserts value is Record<string, unknown> {
  if (
    !isRecord(value) ||
    value.timestamp !== manifest.timestamp ||
    value.granularity !== manifest.granularity ||
    value.currency !== manifest.currency ||
    value.calculationVersion !== manifest.calculationVersion
  ) {
    throw contractError()
  }
}

function validatePortfolio(
  value: unknown,
  manifest: ExactPortfolioSnapshotManifest
): PortfolioSnapshotData {
  validateCommonIdentity(value, manifest)
  if (
    !currency(value.currency) ||
    !Array.isArray(value.accounts) ||
    value.accounts.length !== manifest.accounts.length ||
    !Array.isArray(value.aggregatePositions)
  ) {
    throw contractError()
  }
  const accountById = new Map<string, Record<string, unknown>>()
  let accountPositionCount = 0
  for (const [index, account] of value.accounts.entries()) {
    const selector = manifest.accounts[index]
    if (
      selector === undefined ||
      !isRecord(account) ||
      !isRecord(account.account) ||
      account.account.accountId !== selector.accountId ||
      account.primarySnapshotId !== selector.snapshotId ||
      !trimmedNonBlankString(account.snapshotId) ||
      !trimmedNonBlankString(account.currency) ||
      account.currency !== account.account.currency ||
      !currency(account.currency) ||
      !Array.isArray(account.positions)
    ) {
      throw contractError()
    }
    for (const position of account.positions) {
      validatePortfolioPosition(position, account.currency)
    }
    validatePortfolioSummary(account.summary, account.positions.length)
    accountPositionCount += account.positions.length
    accountById.set(selector.accountId, account)
  }
  for (const item of value.aggregatePositions) {
    if (
      !isRecord(item) ||
      !trimmedNonBlankString(item.accountId) ||
      !trimmedNonBlankString(item.accountName) ||
      !currency(item.accountCurrency)
    ) {
      throw contractError()
    }
    const account = accountById.get(item.accountId)
    if (
      account === undefined ||
      !isRecord(account.account) ||
      item.accountName !== account.account.name ||
      item.accountCurrency !== account.account.currency
    ) {
      throw contractError()
    }
    validatePortfolioPosition(item.position, value.currency)
  }
  if (value.aggregatePositions.length !== accountPositionCount) {
    throw contractError()
  }
  validatePortfolioSummary(value.summary, value.aggregatePositions.length)
  return value as PortfolioSnapshotData
}

function validateDashboard(
  value: unknown,
  manifest: ExactPortfolioSnapshotManifest
): DashboardSnapshotData {
  validateCommonIdentity(value, manifest)
  if (
    !currency(value.currency) ||
    !Array.isArray(value.accounts) ||
    value.accounts.length !== manifest.accounts.length ||
    !Array.isArray(value.assetTypeAllocations) ||
    !Array.isArray(value.topPositions)
  ) {
    throw contractError()
  }
  validateDashboardSummary(value.summary)
  const expectedAccountIds = new Set(manifest.accounts.map((account) => account.accountId))
  const actualAccountIds = new Set<string>()
  for (const account of value.accounts) {
    if (
      !isRecord(account) ||
      !trimmedNonBlankString(account.accountId) ||
      !trimmedNonBlankString(account.primarySnapshotId) ||
      !trimmedNonBlankString(account.snapshotId) ||
      !currency(account.outputCurrency) ||
      !currency(account.accountCurrency) ||
      account.outputCurrency !== account.accountCurrency ||
      !exactDecimal(account.totalValue, MONEY) ||
      !exactDecimal(account.cashValue, MONEY) ||
      !exactDecimal(account.investmentValue, MONEY) ||
      !exactDecimal(account.liabilitiesValue, MONEY) ||
      !exactDecimal(account.unrealizedPnlValue, MONEY) ||
      !nonNegativeInteger(account.positionCount) ||
      !expectedAccountIds.has(account.accountId) ||
      actualAccountIds.has(account.accountId)
    ) {
      throw contractError()
    }
    const selector = manifest.accounts.find((item) => item.accountId === account.accountId)
    if (selector === undefined || account.primarySnapshotId !== selector.snapshotId) {
      throw contractError()
    }
    actualAccountIds.add(account.accountId)
  }
  if (actualAccountIds.size !== expectedAccountIds.size) {
    throw contractError()
  }
  for (const allocation of value.assetTypeAllocations) {
    if (
      !isRecord(allocation) ||
      !exactDecimal(allocation.value, MONEY) ||
      !exactDecimal(allocation.allocationPct, PERCENTAGE) ||
      !nonNegativeInteger(allocation.accountCount) ||
      !nonNegativeInteger(allocation.positionCount)
    ) {
      throw contractError()
    }
  }
  for (const position of value.topPositions) {
    if (
      !isRecord(position) ||
      !trimmedNonBlankString(position.accountId) ||
      !expectedAccountIds.has(position.accountId) ||
      !exactDecimal(position.value, MONEY) ||
      position.valueCurrency !== value.currency ||
      !exactDecimal(position.unrealizedPnl, QUANTITY) ||
      !exactDecimal(position.allocationPct, PERCENTAGE)
    ) {
      throw contractError()
    }
  }
  return value as DashboardSnapshotData
}

async function runSnapshotWorkflow<T>(
  identity: ServerIdentity,
  kind: WorkflowKind,
  api: PythonSnapshotApi = createPythonSnapshotApi(identity)
): Promise<SnapshotWorkflowResult<T>> {
  const refresh = validateRefresh(await api.recalculateSnapshotRefresh())
  if (refresh.manifest === null) {
    return {
      status: "empty",
      refresh: refresh.summary,
    }
  }

  if (kind === "portfolio") {
    const data = validatePortfolio(
      await api.readPortfolioSnapshot(refresh.manifest),
      refresh.manifest
    )
    return {
      status: "ready",
      refresh: refresh.summary,
      data: data as T,
    }
  }

  const data = validateDashboard(
    await api.readDashboardSnapshot(refresh.manifest),
    refresh.manifest
  )
  return {
    status: "ready",
    refresh: refresh.summary,
    data: data as T,
  }
}

export function runPortfolioSnapshotWorkflow(
  identity: ServerIdentity,
  api?: PythonSnapshotApi
): Promise<SnapshotWorkflowResult<PortfolioSnapshotData>> {
  return runSnapshotWorkflow(identity, "portfolio", api)
}

export function runDashboardSnapshotWorkflow(
  identity: ServerIdentity,
  api?: PythonSnapshotApi
): Promise<SnapshotWorkflowResult<DashboardSnapshotData>> {
  return runSnapshotWorkflow(identity, "dashboard", api)
}
