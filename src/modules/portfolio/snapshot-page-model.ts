import type { PortfolioSnapshotData } from "@/modules/python-api/snapshot-workflow-contract"

type PortfolioAccountSnapshot = PortfolioSnapshotData["accounts"][number]
type PortfolioSnapshotPosition = PortfolioAccountSnapshot["positions"][number]

export type PortfolioPagePosition = Readonly<{
  accountId: string
  accountName: string
  accountCurrency: string
  allocationPct: string
  position: PortfolioSnapshotPosition
}>

export type PortfolioPageAllocation = Readonly<{
  key: string
  name: string
  allocationPct: string
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
  allocations: readonly PortfolioPageAllocation[]
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
    allocationPct: position.allocationPct,
    position,
  }))
}

function accountView(account: PortfolioAccountSnapshot): PortfolioPageAccountView {
  return {
    scope: "account",
    accountId: account.account.accountId,
    accountCurrency: account.account.currency,
    label: account.account.name,
    currency: account.currency,
    summary: account.summary,
    positions: positionRows(account),
    allocations: account.positions.map((position) => ({
      key: position.listingId,
      name: position.symbol,
      allocationPct: position.allocationPct,
    })),
  }
}

export function buildPortfolioPageModel(data: PortfolioSnapshotData): PortfolioPageModel {
  const accounts = data.accounts.map(accountView)
  return {
    timestamp: data.asOf,
    granularity: "current",
    calculationVersion: data.calculationVersion,
    currency: data.currency,
    aggregate: {
      scope: "aggregate",
      accountId: null,
      label: "Vše",
      currency: data.currency,
      summary: data.summary,
      positions: data.aggregatePositions.map((item) => ({
        accountId: item.accountId,
        accountName: item.accountName,
        accountCurrency: item.accountCurrency,
        allocationPct: item.portfolioAllocationPct,
        position: item.position,
      })),
      allocations: data.aggregatePositions.map((item) => ({
        key: `${item.accountId}:${item.position.listingId}`,
        name: `${item.position.symbol} · ${item.accountName}`,
        allocationPct: item.portfolioAllocationPct,
      })),
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
