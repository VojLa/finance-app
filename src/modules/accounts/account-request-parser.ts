import type { CreateAccountRequest, UpdateAccountRequest } from "./account-contract"

const CREATE_KEYS = new Set(["name", "type", "currency", "color", "notes"])
const UPDATE_KEYS = new Set(["name", "currency", "color", "notes"])

function requirePlainObject(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError("Invalid account request.")
  }
  const prototype = Object.getPrototypeOf(value)
  if (prototype !== Object.prototype && prototype !== null) {
    throw new TypeError("Invalid account request.")
  }
  return value as Record<string, unknown>
}

function rejectUnknownKeys(value: Record<string, unknown>, allowed: ReadonlySet<string>): void {
  if (Object.keys(value).some((key) => !allowed.has(key))) {
    throw new TypeError("Invalid account request.")
  }
}

function requireString(value: unknown): string {
  if (typeof value !== "string") {
    throw new TypeError("Invalid account request.")
  }
  return value
}

function optionalNullableString(value: unknown): string | null | undefined {
  if (value === undefined || value === null || typeof value === "string") {
    return value
  }
  throw new TypeError("Invalid account request.")
}

export function parseCreateAccountRequest(value: unknown): CreateAccountRequest {
  const object = requirePlainObject(value)
  rejectUnknownKeys(object, CREATE_KEYS)

  const name = requireString(object.name)
  const type = requireString(object.type) as CreateAccountRequest["type"]
  const currency = requireString(object.currency)
  const color = optionalNullableString(object.color)
  const notes = optionalNullableString(object.notes)

  return {
    name,
    type,
    currency,
    ...(color !== undefined ? { color } : {}),
    ...(notes !== undefined ? { notes } : {}),
  }
}

export function parseUpdateAccountRequest(value: unknown): UpdateAccountRequest {
  const object = requirePlainObject(value)
  rejectUnknownKeys(object, UPDATE_KEYS)

  const name = optionalNullableString(object.name)
  const currency = optionalNullableString(object.currency)
  const color = optionalNullableString(object.color)
  const notes = optionalNullableString(object.notes)

  return {
    ...(name !== undefined ? { name } : {}),
    ...(currency !== undefined ? { currency } : {}),
    ...(color !== undefined ? { color } : {}),
    ...(notes !== undefined ? { notes } : {}),
  }
}
