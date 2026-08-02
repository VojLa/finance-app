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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string"
}

export function isPythonAccount(value: unknown): value is PythonAccount {
  if (!isRecord(value)) {
    return false
  }
  return (
    typeof value.id === "string" &&
    value.id.trim().length > 0 &&
    typeof value.name === "string" &&
    value.name.trim().length > 0 &&
    typeof value.type === "string" &&
    value.type.trim().length > 0 &&
    typeof value.currency === "string" &&
    value.currency.trim().length > 0 &&
    isNullableString(value.color) &&
    isNullableString(value.notes) &&
    typeof value.role === "string" &&
    value.role.trim().length > 0 &&
    typeof value.relation_type === "string" &&
    value.relation_type.trim().length > 0 &&
    typeof value.is_archived === "boolean" &&
    typeof value.created_at === "string" &&
    value.created_at.trim().length > 0 &&
    typeof value.updated_at === "string" &&
    value.updated_at.trim().length > 0
  )
}

export function isPythonAccountList(value: unknown): value is PythonAccount[] {
  return Array.isArray(value) && value.every(isPythonAccount)
}

export function isAccountApiErrorResponse(value: unknown): value is AccountApiErrorResponse {
  if (!isRecord(value) || !isRecord(value.error)) {
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
