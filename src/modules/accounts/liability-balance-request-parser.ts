import type { CreateManualLiabilityBalanceRequest } from "./liability-balance-contract"

const REQUEST_KEYS = new Set([
  "effectiveAt",
  "currency",
  "outstandingPrincipal",
  "accruedInterest",
  "feesOutstanding",
])

function requirePlainObject(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError("Invalid liability balance request.")
  }
  const prototype = Object.getPrototypeOf(value)
  if (prototype !== Object.prototype && prototype !== null) {
    throw new TypeError("Invalid liability balance request.")
  }
  return value as Record<string, unknown>
}

function requireString(value: unknown): string {
  if (typeof value !== "string") {
    throw new TypeError("Invalid liability balance request.")
  }
  return value
}

export function parseCreateManualLiabilityBalanceRequest(
  value: unknown
): CreateManualLiabilityBalanceRequest {
  const object = requirePlainObject(value)
  if (
    Object.keys(object).length !== REQUEST_KEYS.size ||
    Object.keys(object).some((key) => !REQUEST_KEYS.has(key))
  ) {
    throw new TypeError("Invalid liability balance request.")
  }
  return {
    effectiveAt: requireString(object.effectiveAt),
    currency: requireString(object.currency),
    outstandingPrincipal: requireString(object.outstandingPrincipal),
    accruedInterest: requireString(object.accruedInterest),
    feesOutstanding: requireString(object.feesOutstanding),
  }
}
