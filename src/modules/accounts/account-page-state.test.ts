import { describe, expect, it } from "vitest"

import { isActionErrorForAccount, type AccountActionState } from "./account-page-state"

describe("account action error scope", () => {
  it.each(["update", "archive"] as const)("%s error belongs only to its account", (action) => {
    const state: AccountActionState = {
      status: "error",
      action,
      accountId: "account-1",
      message: "Safe failure.",
    }

    expect(isActionErrorForAccount(state, action, "account-1")).toBe(true)
    expect(isActionErrorForAccount(state, action, "account-2")).toBe(false)
  })
})
