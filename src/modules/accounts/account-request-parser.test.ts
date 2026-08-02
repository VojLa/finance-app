import { describe, expect, it } from "vitest"

import { parseCreateAccountRequest, parseUpdateAccountRequest } from "./account-request-parser"

describe("account request allowlists", () => {
  it("copies only the exact create fields", () => {
    const input = {
      name: "Broker",
      type: "broker",
      currency: "EUR",
      color: null,
      notes: "Long term",
    }
    const parsed = parseCreateAccountRequest(input)

    expect(parsed).toEqual(input)
    expect(parsed).not.toBe(input)
  })

  it.each(["userId", "user_id", "sub", "role", "membership", "is_archived", "created_at"])(
    "rejects create field %s",
    (field) => {
      expect(() =>
        parseCreateAccountRequest({
          name: "Broker",
          type: "broker",
          currency: "EUR",
          [field]: "caller-controlled",
        })
      ).toThrow(TypeError)
    }
  )

  it.each(["type", "id", "accountId", "role", "is_archived"])(
    "rejects update field %s",
    (field) => {
      expect(() =>
        parseUpdateAccountRequest({ name: "Updated", [field]: "caller-controlled" })
      ).toThrow(TypeError)
    }
  )

  it("leaves business validation to Python", () => {
    expect(parseCreateAccountRequest({ name: "", type: "future-type", currency: "eur" })).toEqual({
      name: "",
      type: "future-type",
      currency: "eur",
    })
  })
})
