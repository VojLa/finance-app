import type { components } from "@/generated/python-api"

export type CreateManualLiabilityBalanceRequest =
  components["schemas"]["ManualLiabilityBalanceCreateRequest"]
export type ManualLiabilityBalanceResponse =
  components["schemas"]["ManualLiabilityBalanceCreateResponse"]

export type LiabilityBalanceApiErrorResponse = {
  error: {
    code: string
    message: string
  }
}

const RESPONSE_KEYS = [
  "balanceId",
  "accountId",
  "effectiveAt",
  "currency",
  "totalOutstanding",
  "source",
  "status",
] as const
const RESPONSE_KEY_SET = new Set<string>(RESPONSE_KEYS)
const ISO_NAIVE_MILLISECOND = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}$/
const EXACT_MONEY = /^\d{1,12}(?:\.\d{1,6})?$/

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false
  }
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function isExactMoney(value: unknown): value is string {
  return typeof value === "string" && EXACT_MONEY.test(value)
}

function assertExactResponseKeys(value: Record<string, unknown>): void {
  const keys = Object.keys(value)
  if (keys.length !== RESPONSE_KEYS.length || keys.some((key) => !RESPONSE_KEY_SET.has(key))) {
    throw new TypeError("Invalid Python liability balance response.")
  }
}

export function parseManualLiabilityBalanceResponse(
  value: unknown
): ManualLiabilityBalanceResponse {
  if (!isPlainObject(value)) {
    throw new TypeError("Invalid Python liability balance response.")
  }
  assertExactResponseKeys(value)
  if (
    typeof value.balanceId !== "string" ||
    value.balanceId.trim().length === 0 ||
    typeof value.accountId !== "string" ||
    value.accountId.trim().length === 0 ||
    typeof value.effectiveAt !== "string" ||
    !ISO_NAIVE_MILLISECOND.test(value.effectiveAt) ||
    typeof value.currency !== "string" ||
    !/^[A-Z]{3}$/.test(value.currency) ||
    !isExactMoney(value.totalOutstanding) ||
    value.source !== "manual" ||
    (value.status !== "created" && value.status !== "replayed")
  ) {
    throw new TypeError("Invalid Python liability balance response.")
  }
  return {
    balanceId: value.balanceId,
    accountId: value.accountId,
    effectiveAt: value.effectiveAt,
    currency: value.currency,
    totalOutstanding: value.totalOutstanding,
    source: value.source,
    status: value.status,
  }
}

export function isLiabilityBalanceApiErrorResponse(
  value: unknown
): value is LiabilityBalanceApiErrorResponse {
  return (
    isPlainObject(value) &&
    isPlainObject(value.error) &&
    typeof value.error.code === "string" &&
    typeof value.error.message === "string"
  )
}
