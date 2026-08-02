export type AccountAction = "create" | "update" | "archive"

export type AccountActionState =
  | { status: "idle" }
  | { status: "submitting"; action: AccountAction; accountId?: string }
  | {
      status: "error"
      action: AccountAction
      accountId?: string
      message: string
    }

export function isActionErrorForAccount(
  state: AccountActionState,
  action: "update" | "archive",
  accountId: string
): state is Extract<AccountActionState, { status: "error" }> {
  return state.status === "error" && state.action === action && state.accountId === accountId
}
