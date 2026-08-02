import type { components } from "@/generated/python-api"

export type PythonAccount = components["schemas"]["AccountResponse"]
export type CreateAccountRequest = components["schemas"]["AccountCreateRequest"]
export type UpdateAccountRequest = components["schemas"]["AccountUpdateRequest"]

export type AccountApiErrorResponse = {
  error: {
    code: string
    message: string
  }
}

export type AccountPageModel = {
  id: string
  name: string
  type: PythonAccount["type"]
  currency: string
  color: string | null
  notes: string | null
  role: PythonAccount["role"]
  relationType: PythonAccount["relation_type"]
  isArchived: boolean
}

export const PYTHON_ACCOUNT_TYPES = [
  "bank",
  "cash",
  "savings",
  "broker",
  "exchange",
  "crypto_wallet",
  "credit_card",
  "loan",
  "mortgage",
] as const satisfies readonly PythonAccount["type"][]

export const PYTHON_ACCOUNT_ROLES = [
  "owner",
  "admin",
  "editor",
  "viewer",
] as const satisfies readonly PythonAccount["role"][]

export const PYTHON_ACCOUNT_RELATION_TYPES = [
  "owner",
  "joint_owner",
  "manager",
  "beneficiary",
  "collaborator",
] as const satisfies readonly PythonAccount["relation_type"][]

const ACCOUNT_RESPONSE_KEYS = [
  "id",
  "name",
  "type",
  "currency",
  "color",
  "notes",
  "is_archived",
  "role",
  "relation_type",
  "created_at",
  "updated_at",
] as const

const ACCOUNT_RESPONSE_KEY_SET = new Set<string>(ACCOUNT_RESPONSE_KEYS)
const ISO_DATE_TIME =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))?$/

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false
  }
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string"
}

function isAccountType(value: unknown): value is PythonAccount["type"] {
  return typeof value === "string" && (PYTHON_ACCOUNT_TYPES as readonly string[]).includes(value)
}

function isAccountRole(value: unknown): value is PythonAccount["role"] {
  return typeof value === "string" && (PYTHON_ACCOUNT_ROLES as readonly string[]).includes(value)
}

function isAccountRelationType(value: unknown): value is PythonAccount["relation_type"] {
  return (
    typeof value === "string" &&
    (PYTHON_ACCOUNT_RELATION_TYPES as readonly string[]).includes(value)
  )
}

function isIsoDateTime(value: unknown): value is string {
  if (typeof value !== "string") {
    return false
  }
  const match = ISO_DATE_TIME.exec(value)
  if (!match) {
    return false
  }
  const [, year, month, day, hour, minute, second, , offsetHour, offsetMinute] = match
  const yearValue = Number(year)
  const monthValue = Number(month)
  const dayValue = Number(day)
  const hourValue = Number(hour)
  const minuteValue = Number(minute)
  const secondValue = Number(second)
  const offsetHourValue = offsetHour === undefined ? 0 : Number(offsetHour)
  const offsetMinuteValue = offsetMinute === undefined ? 0 : Number(offsetMinute)
  const daysInMonth =
    monthValue >= 1 && monthValue <= 12
      ? new Date(Date.UTC(yearValue, monthValue, 0)).getUTCDate()
      : 0

  return (
    dayValue >= 1 &&
    dayValue <= daysInMonth &&
    hourValue <= 23 &&
    minuteValue <= 59 &&
    secondValue <= 59 &&
    offsetHourValue <= 23 &&
    offsetMinuteValue <= 59 &&
    Number.isFinite(Date.parse(value))
  )
}

function assertExactResponseKeys(value: Record<string, unknown>): void {
  const keys = Object.keys(value)
  if (
    keys.length !== ACCOUNT_RESPONSE_KEYS.length ||
    keys.some((key) => !ACCOUNT_RESPONSE_KEY_SET.has(key))
  ) {
    throw new TypeError("Invalid Python account response.")
  }
}

export function parsePythonAccount(value: unknown): PythonAccount {
  if (!isPlainObject(value)) {
    throw new TypeError("Invalid Python account response.")
  }
  assertExactResponseKeys(value)
  if (
    typeof value.id !== "string" ||
    value.id.trim().length === 0 ||
    typeof value.name !== "string" ||
    value.name.trim().length === 0 ||
    !isAccountType(value.type) ||
    typeof value.currency !== "string" ||
    !/^[A-Z]{3}$/.test(value.currency) ||
    !isNullableString(value.color) ||
    !isNullableString(value.notes) ||
    typeof value.is_archived !== "boolean" ||
    !isAccountRole(value.role) ||
    !isAccountRelationType(value.relation_type) ||
    !isIsoDateTime(value.created_at) ||
    !isIsoDateTime(value.updated_at)
  ) {
    throw new TypeError("Invalid Python account response.")
  }

  return {
    id: value.id,
    name: value.name,
    type: value.type,
    currency: value.currency,
    color: value.color,
    notes: value.notes,
    is_archived: value.is_archived,
    role: value.role,
    relation_type: value.relation_type,
    created_at: value.created_at,
    updated_at: value.updated_at,
  }
}

export function parsePythonAccountList(value: unknown): PythonAccount[] {
  if (!Array.isArray(value)) {
    throw new TypeError("Invalid Python account list response.")
  }
  return value.map(parsePythonAccount)
}

export function isAccountApiErrorResponse(value: unknown): value is AccountApiErrorResponse {
  if (!isPlainObject(value) || !isPlainObject(value.error)) {
    return false
  }
  return typeof value.error.code === "string" && typeof value.error.message === "string"
}

export function toAccountPageModel(account: PythonAccount): AccountPageModel {
  return {
    id: account.id,
    name: account.name,
    type: account.type,
    currency: account.currency,
    color: account.color,
    notes: account.notes,
    role: account.role,
    relationType: account.relation_type,
    isArchived: account.is_archived,
  }
}
