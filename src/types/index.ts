import type { AccountType, AssetType, InvestmentType, ImportSource } from "@prisma/client"

export type { AccountType, AssetType, InvestmentType, ImportSource }

export interface HoldingWithPrice {
  id: string
  symbol: string
  name: string | null
  assetType: AssetType
  quantity: number
  avgBuyPrice: number
  currency: string
  accountId: string
  currentPrice: number | null
  currentPriceCurrency: string | null
  currentValue: number | null
  unrealizedPnl: number | null
  unrealizedPnlPct: number | null
}

export interface PortfolioSummary {
  totalValue: number
  totalCost: number
  totalUnrealizedPnl: number
  totalUnrealizedPnlPct: number
  holdings: HoldingWithPrice[]
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
