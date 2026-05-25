import type { ParsedInvestmentTransaction } from "@/types"
import type { AssetType, InvestmentType } from "@prisma/client"
import { get, normalizeText, parseCsvRows, type CsvRow } from "../shared/csv"
import { parseNum, sumAbsNums } from "../shared/number"
import { parseIsoDate } from "../shared/date"
import { isFiatCurrency } from "../shared/investment"
import { mapParsedRows, type ParseResult, type RowParseOutcome } from "../shared/result"

const ACTION_MAP: Record<string, InvestmentType> = {
  "market buy": "buy",
  "market sell": "sell",
  "stop buy": "buy",
  "stop sell": "sell",
  "limit buy": "buy",
  "limit sell": "sell",
  "stop loss": "sell",
  "take profit": "sell",
  deposit: "deposit",
  withdrawal: "withdrawal",
  "dividend (ordinary)": "dividend",
  "dividend (dividends paid by us corporations)": "dividend",
  dividend: "dividend",
  "interest on cash": "interest",
  "cash interest": "interest",
  "currency conversion": "currency_conversion",
  "currency conversion fee": "fee",
}

const FEE_FIELDS = [
  "Currency conversion fee",
  "Stamp duty reserve tax",
  "French transaction tax",
  "Finra fee",
]

function detectAssetType(isin: string | null, symbol: string | null): AssetType {
  if (isFiatCurrency(symbol)) return "cash"
  if (isin?.startsWith("IE")) return "etf"
  return "stock"
}

function mapAction(action: string | undefined): InvestmentType | null {
  if (!action) return null
  return ACTION_MAP[normalizeText(action)] ?? null
}

function parseRow(row: CsvRow, accountId: string): RowParseOutcome<ParsedInvestmentTransaction> {
  const type = mapAction(get(row, ["Action", "Type"]))
  const date = parseIsoDate(get(row, ["Time", "Date"]))
  if (!type) {
    return {
      row: null,
      issue: {
        severity: "ignored",
        code: "unsupported_action",
        message: `Unsupported Trading212 action: ${get(row, ["Action", "Type"]) || "unknown"}.`,
      },
    }
  }
  if (!date) {
    return {
      row: null,
      issue: {
        severity: "warning",
        code: "missing_date",
        message: "Trading212 row is missing a valid date.",
      },
    }
  }

  const isin = get(row, ["ISIN"]) || null
  const symbol = get(row, ["Ticker", "Symbol"]) || null

  return {
    row: {
      date,
      type,
      symbol,
      isin,
      name: get(row, ["Name"]) || null,
      assetType: isin || symbol ? detectAssetType(isin, symbol) : null,
      quantity: parseNum(get(row, ["No. of shares", "Quantity"])),
      pricePerUnit: parseNum(get(row, ["Price / share", "Price per share", "Price"])),
      priceCurrency:
        get(row, ["Currency (Price / share)", "Currency (Price)", "Price currency"]) || null,
      exchangeRate: parseNum(get(row, ["Exchange rate", "Exchange Rate"])),
      totalAmount: parseNum(get(row, ["Total", "Amount"])),
      totalCurrency: get(row, ["Currency (Total)", "Currency (Amount)", "Currency"]) || null,
      fee: sumAbsNums(row, FEE_FIELDS),
      feeCurrency:
        get(row, [
          "Currency (Currency conversion fee)",
          "Currency (Stamp duty reserve tax)",
          "Currency (French transaction tax)",
          "Currency (Finra fee)",
        ]) || null,
      realizedPnl: parseNum(get(row, ["Result", "Realized P/L"])),
      realizedPnlCurrency: get(row, ["Currency (Result)", "Currency (Realized P/L)"]) || null,
      externalId: get(row, ["ID", "Transaction ID"]) || null,
      accountId,
    },
  }
}

export function parseTrading212Result(
  csvText: string,
  accountId: string
): ParseResult<ParsedInvestmentTransaction> {
  return mapParsedRows(parseCsvRows(csvText), (row) => parseRow(row, accountId))
}

export function parseTrading212(csvText: string, accountId: string): ParsedInvestmentTransaction[] {
  return parseTrading212Result(csvText, accountId).rows
}
