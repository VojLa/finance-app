import type { components } from "@/generated/python-api"

export type PythonSnapshotRefreshResponse =
  components["schemas"]["UserSnapshotRefreshRecalculateResponse"]
export type ExactPortfolioSnapshotManifest =
  components["schemas"]["ExactPortfolioSnapshotSetRequest"]
export type LegacyPortfolioSnapshotData = components["schemas"]["MultiAccountPortfolioResponse"]
export type LegacyDashboardSnapshotData = components["schemas"]["DashboardSnapshotResponse"]

type GeneratedPortfolioPosition = components["schemas"]["PortfolioSnapshotPositionResponse"]
type GeneratedPortfolioAccount = components["schemas"]["CurrentPortfolioAccountResponse"]
type GeneratedPortfolioSummary = components["schemas"]["PortfolioSnapshotSummaryResponse"]
type GeneratedAggregateSummary = components["schemas"]["MultiAccountPortfolioSummaryResponse"]
type GeneratedPortfolio = components["schemas"]["CurrentPortfolioResponse"]
export type PythonCurrentPortfolioResponse = GeneratedPortfolio

type PortfolioSummaryValues = {
  cashValue: string
  investmentValue: string
  liabilitiesValue: string
  totalValue: string
  feesValue: string
  taxesValue: string
}

type CompleteSummaryEvidence<T> = Omit<
  T,
  | keyof PortfolioSummaryValues
  | "investmentCostBasis"
  | "netDepositsValue"
  | "netDepositsByCurrency"
  | "realizedPnlValue"
  | "unrealizedPnlValue"
> &
  PortfolioSummaryValues & {
    investmentCostBasis: string
    netDepositsValue: string
    netDepositsByCurrency: components["schemas"]["PortfolioCurrencyAmountResponse"][]
    realizedPnlValue: string
    unrealizedPnlValue: string
  }

type IncompleteSummaryEvidence<T> = Omit<
  T,
  | keyof PortfolioSummaryValues
  | "investmentCostBasis"
  | "netDepositsValue"
  | "netDepositsByCurrency"
  | "realizedPnlValue"
  | "unrealizedPnlValue"
> &
  PortfolioSummaryValues & {
    investmentCostBasis: null
    netDepositsValue: null
    netDepositsByCurrency: null
    realizedPnlValue: null
    unrealizedPnlValue: null
  }

export type PortfolioSnapshotSummaryData<T extends object = GeneratedPortfolioSummary> =
  | CompleteSummaryEvidence<T>
  | IncompleteSummaryEvidence<T>

type PositionValueEvidence = {
  quantity: string
  pricePerUnit: string
  nativeValue: string
}

type CompletePositionCostEvidence = {
  costBasis: string
  costCurrency: string
  unrealizedPnl: string
  nativeCostBasis: string
  nativeCostCurrency: string
  nativeCostBasisByCurrency: components["schemas"]["PortfolioQuantityCurrencyAmountResponse"][]
}

type IncompletePositionCostEvidence = {
  costBasis: null
  costCurrency: null
  unrealizedPnl: null
  nativeCostBasis: null
  nativeCostCurrency: null
  nativeCostBasisByCurrency: null
}

export type PortfolioSnapshotPositionData = Omit<
  GeneratedPortfolioPosition,
  keyof PositionValueEvidence | keyof CompletePositionCostEvidence
> &
  PositionValueEvidence &
  (CompletePositionCostEvidence | IncompletePositionCostEvidence)

export type PortfolioSnapshotAccountData = Omit<
  GeneratedPortfolioAccount,
  "summary" | "positions"
> & {
  summary: PortfolioSnapshotSummaryData
  positions: PortfolioSnapshotPositionData[]
}

type GeneratedAggregatePosition =
  components["schemas"]["MultiAccountPortfolioAggregatePositionResponse"]

export type PortfolioSnapshotData = Omit<
  GeneratedPortfolio,
  "summary" | "accounts" | "aggregatePositions"
> & {
  summary: PortfolioSnapshotSummaryData<GeneratedAggregateSummary>
  accounts: PortfolioSnapshotAccountData[]
  aggregatePositions: (Omit<GeneratedAggregatePosition, "position"> & {
    position: PortfolioSnapshotPositionData
  })[]
}

type GeneratedDashboard = components["schemas"]["CurrentDashboardResponse"]
export type PythonCurrentDashboardResponse = GeneratedDashboard
type GeneratedDashboardSummary = components["schemas"]["DashboardSnapshotSummaryResponse"]
type GeneratedDashboardAccount = components["schemas"]["CurrentDashboardAccountResponse"]

type DashboardSummaryValues = {
  totalValue: string
  assetsValue: string
  liabilitiesValue: string
  cashValue: string
  investmentValue: string
  feesValue: string
  taxesValue: string
}

type DashboardCompleteEvidence = {
  investmentCostBasis: string
  netDepositsValue: string
  realizedPnlValue: string
  unrealizedPnlValue: string
}

type DashboardIncompleteEvidence = {
  investmentCostBasis: null
  netDepositsValue: null
  realizedPnlValue: null
  unrealizedPnlValue: null
}

export type DashboardSnapshotSummaryData = Omit<
  GeneratedDashboardSummary,
  keyof DashboardSummaryValues | keyof DashboardCompleteEvidence
> &
  DashboardSummaryValues &
  (DashboardCompleteEvidence | DashboardIncompleteEvidence)

type DashboardAccountValues = {
  totalValue: string
  cashValue: string
  investmentValue: string
  liabilitiesValue: string
}

type DashboardAccountCompleteEvidence = {
  netDepositsValue: string
  unrealizedPnlValue: string
}

type DashboardAccountIncompleteEvidence = {
  netDepositsValue: null
  unrealizedPnlValue: null
}

export type DashboardSnapshotAccountData = Omit<
  GeneratedDashboardAccount,
  keyof DashboardAccountValues | keyof DashboardAccountCompleteEvidence
> &
  DashboardAccountValues &
  (DashboardAccountCompleteEvidence | DashboardAccountIncompleteEvidence)

export type DashboardSnapshotData = Omit<GeneratedDashboard, "summary" | "accounts"> & {
  summary: DashboardSnapshotSummaryData
  accounts: DashboardSnapshotAccountData[]
}

export type SnapshotRefreshSummary = {
  netWorthSnapshotId: string
  netWorthStatus: "created" | "replayed"
  timestamp: string
  granularity: string
  currency: string
  calculationVersion: number
  refreshAccountCount: number
  reuseOnlyAccountCount: number
  createdAccountSnapshotCount: number
  replayedAccountSnapshotCount: number
  reusedAccountSnapshotCount: number
  selectedAccountSnapshotCount: number
}

export type CurrentValueSummary = {
  asOf: string
  baselineTimestamp: string
  historyAnchorSnapshotId: string
  currency: string
  calculationVersion: number
}

export type ReadySnapshotWorkflowResult<T> = {
  status: "ready"
  current: CurrentValueSummary
  data: T
}

export type SnapshotWorkflowResult<T> = ReadySnapshotWorkflowResult<T>

export type SnapshotWorkflowErrorResponse = {
  error: {
    code: string
    message: string
  }
}
