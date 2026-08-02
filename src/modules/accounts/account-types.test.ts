import { describe, expect, it } from "vitest"

import { ACCOUNT_TYPES, ACCOUNT_TYPE_LABELS } from "@/lib/constants"
import { PYTHON_ACCOUNT_TYPES } from "./account-contract"

describe("account type UI coverage", () => {
  it("offers exactly every Python account type", () => {
    expect(ACCOUNT_TYPES.map(({ value }) => value)).toEqual(PYTHON_ACCOUNT_TYPES)
    expect(Object.keys(ACCOUNT_TYPE_LABELS)).toEqual(PYTHON_ACCOUNT_TYPES)
  })
})
