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
  if (!Array.isArray(value.accounts) || value.accounts.length !== manifest.accounts.length) {
    throw contractError()
  }
  for (const [index, account] of value.accounts.entries()) {
    const selector = manifest.accounts[index]
    if (
      selector === undefined ||
      !isRecord(account) ||
      !isRecord(account.account) ||
      account.account.accountId !== selector.accountId ||
      account.snapshotId !== selector.snapshotId
    ) {
      throw contractError()
    }
  }
  return value as PortfolioSnapshotData
}

function validateDashboard(
  value: unknown,
  manifest: ExactPortfolioSnapshotManifest
): DashboardSnapshotData {
  validateCommonIdentity(value, manifest)
  if (!Array.isArray(value.accounts) || value.accounts.length !== manifest.accounts.length) {
    throw contractError()
  }
  const expectedAccountIds = new Set(manifest.accounts.map((account) => account.accountId))
  const actualAccountIds = new Set<string>()
  for (const account of value.accounts) {
    if (
      !isRecord(account) ||
      !trimmedNonBlankString(account.accountId) ||
      !expectedAccountIds.has(account.accountId) ||
      actualAccountIds.has(account.accountId)
    ) {
      throw contractError()
    }
    actualAccountIds.add(account.accountId)
  }
  if (actualAccountIds.size !== expectedAccountIds.size) {
    throw contractError()
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
