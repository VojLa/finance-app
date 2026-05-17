import Papa from "papaparse"
import type { ParsedInvestmentTransaction } from "@/types"
import type { InvestmentType, AssetType } from "@prisma/client"

const ACTION_MAP: Record<string, InvestmentType> = {
  "Market buy": "buy",
  "Market sell": "sell",
  "Deposit": "deposit",
  "Withdrawal": "withdrawal",
  "Dividend (Ordinary)": "dividend",
  "Dividend (Dividends paid by us corporations)": "dividend",
  "Interest on cash": "interest",
  "Currency conversion": "currency_conversion",
}

function detectAssetType(isin: string | null): AssetType {
  if (isin?.startsWith("IE")) return "etf"
  return "stock"
}

function parseNum(val: string | undefined): number | null {
  if (!val || val.trim() === "") return null
  const n = parseFloat(val)
  return isNaN(n) ? null : n
}

export function parseTrading212(csvText: string, accountId: string): ParsedInvestmentTransaction[] {
  const result = Papa.parse<Record<string, string>>(csvText, {
    header: true,
    skipEmptyLines: true,
  })

  return result.data
    .map((row): ParsedInvestmentTransaction | null => {
      const type = ACTION_MAP[row["Action"]]
      if (!type) return null

      const isin = row["ISIN"] || null
      return {
        date: new Date(row["Time"]),
        type,
        symbol: row["Ticker"] || null,
        isin,
        name: row["Name"] || null,
        assetType: isin ? detectAssetType(isin) : null,
        quantity: parseNum(row["No. of shares"]),
        pricePerUnit: parseNum(row["Price / share"]),
        priceCurrency: row["Currency (Price / share)"] || null,
        exchangeRate: parseNum(row["Exchange rate"]),
        totalAmount: parseNum(row["Total"]),
        totalCurrency: row["Currency (Total)"] || null,
        fee: parseNum(row["Currency conversion fee"]),
        feeCurrency: row["Currency (Currency conversion fee)"] || null,
        realizedPnl: parseNum(row["Result"]),
        realizedPnlCurrency: row["Currency (Result)"] || null,
        externalId: row["ID"] || null,
        accountId,
      }
    })
    .filter((t): t is ParsedInvestmentTransaction => t !== null)
}
