import type { PortfolioSnapshotData } from "@/modules/python-api/snapshot-workflow-contract"

type PortfolioAccountSnapshot = PortfolioSnapshotData["accounts"][number]
type PortfolioSnapshotPosition = PortfolioAccountSnapshot["positions"][number]

export type PortfolioPagePosition = Readonly<{
  accountId: string
  accountName: string
  accountCurrency: string
  position: PortfolioSnapshotPosition
}>

export type PortfolioPageSummary =
  | PortfolioSnapshotData["summary"]
  | PortfolioAccountSnapshot["summary"]

export type PortfolioPageView = Readonly<{
  scope: "aggregate" | "account"
  accountId: string | null
  label: string
  currency: string
  summary: PortfolioPageSummary
  positions: readonly PortfolioPagePosition[]
  hasServerAllocation: boolean
}>

export type PortfolioPageAccountView = PortfolioPageView &
  Readonly<{
    scope: "account"
    accountId: string
    accountCurrency: string
  }>

export type PortfolioPageModel = Readonly<{
  timestamp: string
  granularity: string
  calculationVersion: number
  currency: string
  aggregate: PortfolioPageView
  accounts: readonly PortfolioPageAccountView[]
}>

function positionRows(account: PortfolioAccountSnapshot): PortfolioPagePosition[] {
  return account.positions.map((position) => ({
    accountId: account.account.accountId,
    accountName: account.account.name,
    accountCurrency: account.account.currency,
    position,
  }))
}

function accountView(
  account: PortfolioAccountSnapshot,
  outputCurrency: string
): PortfolioPageAccountView {
  return {
    scope: "account",
    accountId: account.account.accountId,
    accountCurrency: account.account.currency,
    label: account.account.name,
    currency: outputCurrency,
    summary: account.summary,
    positions: positionRows(account),
    hasServerAllocation: true,
  }
}

export function buildPortfolioPageModel(data: PortfolioSnapshotData): PortfolioPageModel {
  const accounts = data.accounts.map((account) => accountView(account, data.currency))
  return {
    timestamp: data.timestamp,
    granularity: data.granularity,
    calculationVersion: data.calculationVersion,
    currency: data.currency,
    aggregate: {
      scope: "aggregate",
      accountId: null,
      label: "Vše",
      currency: data.currency,
      summary: data.summary,
      positions: data.accounts.flatMap(positionRows),
      hasServerAllocation: data.accounts.length === 1,
    },
    accounts,
  }
}

export function selectPortfolioAccountView(
  model: PortfolioPageModel,
  accountId: string
): PortfolioPageAccountView | null {
  return model.accounts.find((account) => account.accountId === accountId) ?? null
}
