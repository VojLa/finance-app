import type { PythonAccount } from "./account-contract"

export function canEditAccount(role: PythonAccount["role"]): boolean {
  switch (role) {
    case "owner":
    case "admin":
    case "editor":
      return true
    case "viewer":
      return false
  }
}

export function canArchiveAccount(role: PythonAccount["role"]): boolean {
  switch (role) {
    case "owner":
    case "admin":
      return true
    case "editor":
    case "viewer":
      return false
  }
}

export function isSharedAccount(relationType: PythonAccount["relation_type"]): boolean {
  return relationType !== "owner"
}

export function accountRoleLabel(role: PythonAccount["role"]): string {
  switch (role) {
    case "owner":
      return "Vlastník"
    case "admin":
      return "Administrátor"
    case "editor":
      return "Editor"
    case "viewer":
      return "Prohlížející"
  }
}
