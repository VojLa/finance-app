import type { AccountType, AssetType, InvestmentType, ImportSource } from "@prisma/client"

export type { AccountType, AssetType, InvestmentType, ImportSource }

export interface HoldingWithPrice {
  id: string
  symbol: string
  name: string | null
  assetType: AssetType
  quantity: number
  avgBuyPrice: number
  avgBuyPriceCzk: number | null
  currency: string
  accountId: string
  accountName: string | null
  currentPrice: number | null
  currentPriceCurrency: string | null
  currentValue: number | null
  currentValueCzk: number | null
  unrealizedPnl: number | null
  unrealizedPnlCzk: number | null
  unrealizedPnlPct: number | null
}

export interface PortfolioSummary {
  totalValueCzk: number
  totalCostCzk: number
  totalUnrealizedPnlCzk: number
  totalUnrealizedPnlPct: number
  totalRealizedPnlCzk: number
  czkRates: Record<string, number>
  holdings: HoldingWithPrice[]
  accounts: { id: string; name: string; type: string }[]
  warnings: { symbol: string; issue: string }[]
}

export interface AccountCash {
  accountId: string
  accountName: string
  accountType: string
  color: string | null
  balances: { currency: string; amount: number; amountCzk: number }[]
  totalCzk: number
}

export interface CashSummary {
  accounts: AccountCash[]
  totalCashCzk: number
  czkRates: Record<string, number>
}

export interface ParsedInvestmentTransaction {
  date: Date
  type: InvestmentType
  symbol?: string | null
  isin?: string | null
  name?: string | null
  assetType?: AssetType | null
  quantity?: number | null
  pricePerUnit?: number | null
  priceCurrency?: string | null
  totalAmount?: number | null
  totalCurrency?: string | null
  fee?: number | null
  feeCurrency?: string | null
  exchangeRate?: number | null
  orderId?: string | null
  externalId?: string | null
  realizedPnl?: number | null
  realizedPnlCurrency?: string | null
  accountId: string
}
