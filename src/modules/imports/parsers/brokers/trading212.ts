import type { ParsedInvestmentEvent } from "@/types"
import {
  parseSingleRowInvestmentCsv,
  type InvestmentFieldKeys,
  type SingleRowInvestmentParserDefinition,
} from "../shared/parser"
import type { ParseResult } from "../shared/result"

const FIELD_KEYS: InvestmentFieldKeys = {
  type: ["Action"],
  date: ["Time"],
  isin: ["ISIN"],
  symbol: ["Ticker"],
  name: ["Name"],
  quantity: ["No. of shares", "Quantity"],
  pricePerUnit: ["Price / share", "Price per share", "Price"],
  priceCurrency: ["Currency (Price / share)", "Currency (Price)", "Price currency"],
  exchangeRate: ["Exchange rate", "Exchange Rate"],
  totalAmount: ["Total", "Amount"],
  totalCurrency: ["Currency (Total)", "Currency (Amount)", "Currency"],
  conversionFromAmount: ["Currency conversion from amount"],
  conversionFromCurrency: ["Currency (Currency conversion from amount)"],
  conversionToAmount: ["Currency conversion to amount"],
  conversionToCurrency: ["Currency (Currency conversion to amount)"],
  feeCurrency: [
    "Currency (Currency conversion fee)",
    "Currency (Withholding tax)",
    "Currency (Stamp duty reserve tax)",
    "Currency (French transaction tax)",
    "Currency (Finra fee)",
  ],
  realizedPnl: ["Result", "Realized P/L"],
  realizedPnlCurrency: ["Currency (Result)", "Currency (Realized P/L)"],
  externalId: ["ID", "Transaction ID"],
}

const FEE_FIELDS = [
  "Currency conversion fee",
  "Withholding tax",
  "Stamp duty reserve tax",
  "French transaction tax",
  "Finra fee",
]

const PARSER: SingleRowInvestmentParserDefinition = {
  parserName: "Trading212",
  keys: FIELD_KEYS,
  feeFields: FEE_FIELDS,
}

export function parseTrading212Result(
  csvText: string,
  accountId: string
): ParseResult<ParsedInvestmentEvent> {
  return parseSingleRowInvestmentCsv(csvText, accountId, PARSER)
}

export function parseTrading212(csvText: string, accountId: string): ParsedInvestmentEvent[] {
  return parseTrading212Result(csvText, accountId).rows
}
