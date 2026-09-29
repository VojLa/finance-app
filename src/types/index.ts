export type AssetType = "stock" | "etf" | "crypto" | "commodity" | "cash" | "bond" | "other"

export interface HoldingWithPrice {
  id: string
  symbol: string
  name: string | null
  assetType: AssetType
  quantity: number
  avgBuyPrice: number
  avgBuyPriceCzk: number | null
  currency: string
  listingId: string | null
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
