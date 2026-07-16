import type { ParsedInvestmentEvent } from "@/types"
import { normalizeText } from "../shared/csv"
import {
  parseSingleRowInvestmentCsv,
  type InvestmentFieldKeys,
  type SingleRowInvestmentParserDefinition,
} from "../shared/parser"
import type { ParseResult } from "../shared/result"

const FIELD_KEYS: InvestmentFieldKeys = {
  type: ["Action"],
  date: ["Time", "Time (UTC)"],
  isin: ["ISIN"],
  symbol: ["Ticker"],
  name: ["Name", "Merchant", "Merchant name", "Merchant Name"],
  quantity: ["No. of shares", "Quantity"],
  pricePerUnit: ["Price / share", "Price per share", "Price"],
  priceCurrency: ["Currency (Price / share)", "Currency (Price)", "Price currency"],
  exchangeRate: ["Exchange rate", "Exchange Rate"],
  totalAmount: ["Total", "Amount"],
  totalCurrency: ["Currency (Total)", "Currency (Amount)", "Currency"],
  note: ["Notes", "Note", "Category", "Merchant category", "Card category", "Card Category"],
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
  "Stamp duty reserve tax",
  "French transaction tax",
  "Finra fee",
]

const ACTION_MAP = {
  "card debit": "withdrawal",
  "dividend (dividend)": "dividend",
  "dividend (dividend manufactured payment)": "dividend",
  "dividend (tax exempted)": "dividend",
  "free share": "deposit",
  "free shares": "deposit",
  "free stock": "deposit",
  "free stocks": "deposit",
  "new card cost": "withdrawal",
  "spending cashback": "interest",
} as const

const PARSER: SingleRowInvestmentParserDefinition = {
  parserName: "Trading212",
  keys: FIELD_KEYS,
  actionMap: ACTION_MAP,
  feeFields: FEE_FIELDS,
  requireAssetIdentityForTypes: ["buy", "sell", "staking_reward", "airdrop", "transfer"],
}

const FREE_SHARE_MARKERS = [
  "free share",
  "free shares",
  "free stock",
  "free stocks",
  "bonus share",
  "bonus shares",
  "bonus stock",
  "bonus stocks",
  "referral share",
  "referral shares",
  "promo share",
  "promo shares",
  "promotion share",
  "promotion shares",
]

function isFreeShareRow(row: ParsedInvestmentEvent) {
  const text = normalizeText([row.rawAction, row.note, row.name].filter(Boolean).join(" "))
  return FREE_SHARE_MARKERS.some((marker) => text.includes(marker))
}

export function isTrading212CardDebitRow(row: Pick<ParsedInvestmentEvent, "rawAction">) {
  return normalizeText(row.rawAction ?? "") === "card debit"
}

function isTrading212CardExpenseRow(row: Pick<ParsedInvestmentEvent, "rawAction">) {
  const action = normalizeText(row.rawAction ?? "")
  return action === "card debit" || action === "new card cost"
}

function normalizeCardExpenseRow(row: ParsedInvestmentEvent): ParsedInvestmentEvent {
  const amount = row.totalAmount == null ? row.totalAmount : Math.abs(row.totalAmount)
  const counterparty = row.name || null
  const category = row.note || null
  const action = row.rawAction || "Card debit"

  return {
    ...row,
    type: "withdrawal",
    totalAmount: amount,
    linkedTransactionType: "expense",
    linkedTransactionDescription: counterparty
      ? `${action}: ${counterparty}`
      : action,
    linkedTransactionCounterparty: counterparty,
    linkedTransactionNote: category,
  }
}

function normalizeTrading212Row(row: ParsedInvestmentEvent): ParsedInvestmentEvent {
  if (isTrading212CardExpenseRow(row)) return normalizeCardExpenseRow(row)
  if (!isFreeShareRow(row)) return row

  const hasAsset = Boolean(row.symbol && row.quantity != null)
  return {
    ...row,
    type: hasAsset ? "airdrop" : row.type,
    fee: null,
    feeCurrency: null,
    isPromotional: true,
  }
}

export function parseTrading212Result(
  csvText: string,
  accountId: string
): ParseResult<ParsedInvestmentEvent> {
  const result = parseSingleRowInvestmentCsv(csvText, accountId, PARSER)
  return {
    ...result,
    rows: result.rows.map(normalizeTrading212Row),
  }
}

export function parseTrading212(csvText: string, accountId: string): ParsedInvestmentEvent[] {
  return parseTrading212Result(csvText, accountId).rows
}
