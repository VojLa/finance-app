import type { AssetType, ParsedInvestmentAction, ParsedInvestmentEvent } from "@/types"
import { get, normalizeText, parseCsvRows, type CsvRow, type ParseCsvRowsOptions } from "./csv"
import { parseIsoDate } from "./date"
import { isFiatCurrency } from "./investment"
import { parseNum, sumAbsNums } from "./number"
import {
  mapParsedRows,
  type ParseIssue,
  type ParseIssueSeverity,
  type ParseResult,
  type RowParseOutcome,
} from "./result"

export type InvestmentParseIssueCode =
  | "missing_action"
  | "unsupported_action"
  | "missing_date"
  | "invalid_date"
  | "missing_asset_identity"
  | "missing_quantity"
  | "invalid_quantity"
  | "missing_price"
  | "invalid_price"
  | "missing_price_currency"
  | "missing_total_amount"
  | "invalid_total_amount"
  | "missing_total_currency"
  | "invalid_exchange_rate"
  | "invalid_fee"
  | "missing_fee_currency"
  | "invalid_realized_pnl"
  | "missing_realized_pnl_currency"
  | "missing_external_id"

export type RequiredInvestmentField =
  | "assetIdentity"
  | "isin"
  | "symbol"
  | "name"
  | "assetType"
  | "quantity"
  | "pricePerUnit"
  | "priceCurrency"
  | "exchangeRate"
  | "totalAmount"
  | "totalCurrency"
  | "fee"
  | "feeCurrency"
  | "realizedPnl"
  | "realizedPnlCurrency"
  | "externalId"

export interface InvestmentFieldKeys {
  type: string[]
  date: string[]
  isin?: string[]
  symbol?: string[]
  name?: string[]
  assetType?: string[]
  quantity?: string[]
  pricePerUnit?: string[]
  priceCurrency?: string[]
  exchangeRate?: string[]
  totalAmount?: string[]
  totalCurrency?: string[]
  fee?: string[]
  feeCurrency?: string[]
  conversionFromAmount?: string[]
  conversionFromCurrency?: string[]
  conversionToAmount?: string[]
  conversionToCurrency?: string[]
  realizedPnl?: string[]
  realizedPnlCurrency?: string[]
  externalId?: string[]
}

export interface InvestmentRowParserOptions {
  parserName: string
  accountId: string
  keys: InvestmentFieldKeys
  actionMap?: Record<string, ParsedInvestmentAction>
  feeFields?: string[]
  requiredFields?: RequiredInvestmentField[]
  requireQuantityForTypes?: ParsedInvestmentAction[]
  requireAssetIdentityForTypes?: ParsedInvestmentAction[]
  defaultAssetType?: AssetType
}

export type SingleRowInvestmentParserDefinition = Omit<InvestmentRowParserOptions, "accountId">

export interface ParseSingleRowInvestmentCsvOptions extends SingleRowInvestmentParserDefinition {
  csv?: ParseCsvRowsOptions
}

const DEFAULT_ACTION_MAP: Record<string, ParsedInvestmentAction> = {
  // buy
  buy: "buy",
  purchase: "buy",
  "market buy": "buy",
  "limit buy": "buy",
  "stop buy": "buy",
  "crypto purchase": "buy",
  // sell
  sell: "sell",
  sale: "sell",
  "market sell": "sell",
  "limit sell": "sell",
  "stop sell": "sell",
  "stop loss": "sell",
  "take profit": "sell",
  "crypto sale": "sell",
  // deposit
  deposit: "deposit",
  "fiat deposit": "deposit",
  "crypto deposit": "deposit",
  receive: "deposit",
  incoming: "deposit",
  credit: "deposit",
  "top up": "deposit",
  funding: "deposit",
  // withdrawal
  withdrawal: "withdrawal",
  "fiat withdrawal": "withdrawal",
  "crypto withdrawal": "withdrawal",
  send: "withdrawal",
  outgoing: "withdrawal",
  debit: "withdrawal",
  // dividend
  dividend: "dividend",
  dividends: "dividend",
  "dividend (ordinary)": "dividend",
  "dividend (dividends paid by us corporations)": "dividend",
  "dividend reinvestment": "dividend",
  // interest
  interest: "interest",
  "interest on cash": "interest",
  "cash interest": "interest",
  "savings interest": "interest",
  "earn interest": "interest",
  "lending interest": "interest",
  // currency conversion
  "currency conversion": "currency_conversion",
  "fx conversion": "currency_conversion",
  exchange: "currency_conversion",
  convert: "currency_conversion",
  swap: "currency_conversion",
  // fee
  fee: "fee",
  commission: "fee",
  "currency conversion fee": "fee",
  "transaction fee": "fee",
  "trading fee": "fee",
  "withdrawal fee": "fee",
  "service fee": "fee",
  // transfer
  transfer: "transfer",
  "internal transfer": "transfer",
  "account transfer": "transfer",
  "portfolio transfer": "transfer",
  // staking
  staking: "staking_reward",
  "staking reward": "staking_reward",
  "staking income": "staking_reward",
  "eth2 staking reward": "staking_reward",
  // airdrop
  airdrop: "airdrop",
  fork: "airdrop",
  "token distribution": "airdrop",
}

const DEFAULT_FEE_FIELDS = [
  "Currency conversion fee",
  "Stamp duty reserve tax",
  "French transaction tax",
  "Finra fee",
]

const DEFAULT_QUANTITY_TYPES: ParsedInvestmentAction[] = [
  "buy",
  "sell",
  "staking_reward",
  "airdrop",
  "transfer",
]

const DEFAULT_ASSET_IDENTITY_TYPES: ParsedInvestmentAction[] = [
  "buy",
  "sell",
  "dividend",
  "staking_reward",
  "airdrop",
  "transfer",
]

function issue(
  severity: ParseIssueSeverity,
  code: InvestmentParseIssueCode,
  message: string,
  rowNumber?: number,
  raw?: CsvRow
): ParseIssue {
  return { severity, code, message, rowNumber, raw }
}

function fieldLabel(keys: string[] | undefined, fallback: string): string {
  return keys && keys.length > 0 ? keys.join(" / ") : fallback
}

function getValue(row: CsvRow, keys: string[] | undefined): string | undefined {
  return keys ? get(row, keys) : undefined
}

function parseOptionalNumber(
  row: CsvRow,
  keys: string[] | undefined,
  code: InvestmentParseIssueCode,
  parserName: string,
  issues: ParseIssue[]
): number | null {
  const raw = getValue(row, keys)
  if (!raw) return null

  const parsed = parseNum(raw)
  if (parsed === null) {
    issues.push(
      issue(
        "warning",
        code,
        `${parserName} has invalid number in ${fieldLabel(keys, "numeric field")}: ${raw}.`
      )
    )
  }

  return parsed
}

function mapAction(
  rawAction: string | undefined,
  actionMap: Record<string, ParsedInvestmentAction>
): ParsedInvestmentAction | null {
  if (!rawAction) return null
  return actionMap[normalizeText(rawAction)] ?? null
}

function detectAssetType(
  isin: string | null,
  symbol: string | null,
  explicitAssetType: string | undefined,
  fallback: AssetType
): AssetType {
  const normalized = normalizeText(explicitAssetType)
  if (normalized === "stock") return "stock"
  if (normalized === "etf") return "etf"
  if (normalized === "crypto") return "crypto"
  if (normalized === "cash") return "cash"
  if (normalized === "bond") return "bond"
  if (normalized === "commodity") return "commodity"
  if (isFiatCurrency(symbol)) return "cash"
  if (isin?.startsWith("IE")) return "etf"
  return fallback
}

function hasField(
  field: RequiredInvestmentField,
  requiredFields: RequiredInvestmentField[]
): boolean {
  return requiredFields.includes(field)
}

function addRequiredFieldIssues({
  issues,
  parserName,
  requiredFields,
  type,
  isin,
  symbol,
  quantity,
  pricePerUnit,
  priceCurrency,
  totalAmount,
  totalCurrency,
  fee,
  feeCurrency,
  realizedPnl,
  realizedPnlCurrency,
  externalId,
}: {
  issues: ParseIssue[]
  parserName: string
  requiredFields: RequiredInvestmentField[]
  type: ParsedInvestmentAction
  isin: string | null
  symbol: string | null
  quantity: number | null
  pricePerUnit: number | null
  priceCurrency: string | null
  totalAmount: number | null
  totalCurrency: string | null
  fee: number | null
  feeCurrency: string | null
  realizedPnl: number | null
  realizedPnlCurrency: string | null
  externalId: string | null
}) {
  if (hasField("assetIdentity", requiredFields) && !isin && !symbol) {
    issues.push(
      issue(
        "warning",
        "missing_asset_identity",
        `${parserName} ${type} row is missing ISIN/symbol.`
      )
    )
  }
  if (hasField("quantity", requiredFields) && quantity === null) {
    issues.push(
      issue("warning", "missing_quantity", `${parserName} ${type} row is missing quantity.`)
    )
  }
  if (hasField("pricePerUnit", requiredFields) && pricePerUnit === null) {
    issues.push(issue("warning", "missing_price", `${parserName} ${type} row is missing price.`))
  }
  if (hasField("priceCurrency", requiredFields) && !priceCurrency) {
    issues.push(
      issue(
        "warning",
        "missing_price_currency",
        `${parserName} ${type} row is missing price currency.`
      )
    )
  }
  if (hasField("totalAmount", requiredFields) && totalAmount === null) {
    issues.push(
      issue("warning", "missing_total_amount", `${parserName} ${type} row is missing total amount.`)
    )
  }
  if (hasField("totalCurrency", requiredFields) && !totalCurrency) {
    issues.push(
      issue(
        "warning",
        "missing_total_currency",
        `${parserName} ${type} row is missing total currency.`
      )
    )
  }
  if (hasField("feeCurrency", requiredFields) && fee !== null && !feeCurrency) {
    issues.push(
      issue(
        "warning",
        "missing_fee_currency",
        `${parserName} ${type} row has fee without fee currency.`
      )
    )
  }
  if (
    hasField("realizedPnlCurrency", requiredFields) &&
    realizedPnl !== null &&
    !realizedPnlCurrency
  ) {
    issues.push(
      issue(
        "warning",
        "missing_realized_pnl_currency",
        `${parserName} ${type} row has realized P/L without currency.`
      )
    )
  }
  if (hasField("externalId", requiredFields) && !externalId) {
    issues.push(
      issue("warning", "missing_external_id", `${parserName} ${type} row is missing external ID.`)
    )
  }
}

export function parseInvestmentRow(
  row: CsvRow,
  options: InvestmentRowParserOptions
): RowParseOutcome<ParsedInvestmentEvent> {
  const {
    parserName,
    accountId,
    keys,
    actionMap = DEFAULT_ACTION_MAP,
    feeFields = DEFAULT_FEE_FIELDS,
    requiredFields = [],
    requireQuantityForTypes = DEFAULT_QUANTITY_TYPES,
    requireAssetIdentityForTypes = DEFAULT_ASSET_IDENTITY_TYPES,
    defaultAssetType = "stock",
  } = options

  const actionRaw = getValue(row, keys.type)
  if (!actionRaw) {
    return {
      row: null,
      issues: [issue("warning", "missing_action", `${parserName} row is missing action/type.`)],
    }
  }

  const type = mapAction(actionRaw, actionMap)
  if (!type) {
    return {
      row: null,
      issues: [
        issue("ignored", "unsupported_action", `Unsupported ${parserName} action: ${actionRaw}.`),
      ],
    }
  }

  const dateRaw = getValue(row, keys.date)
  if (!dateRaw) {
    return {
      row: null,
      issues: [issue("warning", "missing_date", `${parserName} ${type} row is missing date.`)],
    }
  }

  const date = parseIsoDate(dateRaw)
  if (!date) {
    return {
      row: null,
      issues: [
        issue("warning", "invalid_date", `${parserName} ${type} row has invalid date: ${dateRaw}.`),
      ],
    }
  }

  const issues: ParseIssue[] = []
  const isin = getValue(row, keys.isin) || null
  const symbol = getValue(row, keys.symbol) || null
  const quantity = parseOptionalNumber(row, keys.quantity, "invalid_quantity", parserName, issues)
  const pricePerUnit = parseOptionalNumber(
    row,
    keys.pricePerUnit,
    "invalid_price",
    parserName,
    issues
  )
  const exchangeRate = parseOptionalNumber(
    row,
    keys.exchangeRate,
    "invalid_exchange_rate",
    parserName,
    issues
  )
  const totalAmount = parseOptionalNumber(
    row,
    keys.totalAmount,
    "invalid_total_amount",
    parserName,
    issues
  )
  const realizedPnl = parseOptionalNumber(
    row,
    keys.realizedPnl,
    "invalid_realized_pnl",
    parserName,
    issues
  )
  const explicitFee = parseOptionalNumber(row, keys.fee, "invalid_fee", parserName, issues)
  const fee = explicitFee ?? sumAbsNums(row, feeFields)
  const conversionFromAmount = parseOptionalNumber(
    row,
    keys.conversionFromAmount,
    "invalid_total_amount",
    parserName,
    issues
  )
  const conversionToAmount = parseOptionalNumber(
    row,
    keys.conversionToAmount,
    "invalid_total_amount",
    parserName,
    issues
  )

  const priceCurrency = getValue(row, keys.priceCurrency) || null
  const totalCurrency = getValue(row, keys.totalCurrency) || null
  const feeCurrency = getValue(row, keys.feeCurrency) || null
  const conversionFromCurrency = getValue(row, keys.conversionFromCurrency) || null
  const conversionToCurrency = getValue(row, keys.conversionToCurrency) || null
  const realizedPnlCurrency = getValue(row, keys.realizedPnlCurrency) || null
  const externalId = getValue(row, keys.externalId) || null

  const effectiveRequiredFields = new Set(requiredFields)
  if (requireQuantityForTypes.includes(type)) effectiveRequiredFields.add("quantity")
  if (requireAssetIdentityForTypes.includes(type)) effectiveRequiredFields.add("assetIdentity")

  addRequiredFieldIssues({
    issues,
    parserName,
    requiredFields: [...effectiveRequiredFields],
    type,
    isin,
    symbol,
    quantity,
    pricePerUnit,
    priceCurrency,
    totalAmount,
    totalCurrency,
    fee,
    feeCurrency,
    realizedPnl,
    realizedPnlCurrency,
    externalId,
  })

  const fatalCodes: InvestmentParseIssueCode[] = [
    "missing_asset_identity",
    "missing_quantity",
    "invalid_quantity",
  ]
  const hasFatalIssue = issues.some((rowIssue) =>
    fatalCodes.includes(rowIssue.code as InvestmentParseIssueCode)
  )

  if (hasFatalIssue) return { row: null, issues }

  return {
    row: {
      date,
      type,
      symbol,
      isin,
      name: getValue(row, keys.name) || null,
      assetType:
        isin || symbol
          ? detectAssetType(isin, symbol, getValue(row, keys.assetType), defaultAssetType)
          : null,
      quantity,
      pricePerUnit,
      priceCurrency,
      exchangeRate,
      totalAmount,
      totalCurrency,
      fee,
      feeCurrency,
      conversionFromAmount,
      conversionFromCurrency,
      conversionToAmount,
      conversionToCurrency,
      realizedPnl,
      realizedPnlCurrency,
      externalId,
      accountId,
    },
    issues: issues.length > 0 ? issues : undefined,
  }
}

export function parseSingleRowInvestmentCsv(
  csvText: string,
  accountId: string,
  options: ParseSingleRowInvestmentCsvOptions
): ParseResult<ParsedInvestmentEvent> {
  const { csv, ...rowOptions } = options

  return mapParsedRows(parseCsvRows(csvText, csv), (row) =>
    parseInvestmentRow(row, {
      ...rowOptions,
      accountId,
    })
  )
}
