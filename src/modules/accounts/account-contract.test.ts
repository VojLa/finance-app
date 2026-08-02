import { describe, expect, it } from "vitest"

import { parsePythonAccount, parsePythonAccountList } from "./account-contract"

const ACCOUNT = {
  id: "account-1",
  name: "Broker",
  type: "broker",
  currency: "EUR",
  color: null,
  notes: null,
  is_archived: false,
  role: "owner",
  relation_type: "owner",
  created_at: "2036-01-01T00:00:00",
  updated_at: "2036-01-01T00:00:00",
}

describe("exact Python account response parser", () => {
  it("copies every allowed field into a new safe object", () => {
    const parsed = parsePythonAccount(ACCOUNT)

    expect(parsed).toEqual(ACCOUNT)
    expect(parsed).not.toBe(ACCOUNT)
  })

  it.each([
    "token",
    "authorization",
    "password_hash",
    "request_id",
    "backend_url",
    "membership",
    "internal_metadata",
  ])("rejects the extra success field %s", (field) => {
    expect(() => parsePythonAccount({ ...ACCOUNT, [field]: "must-not-leak" })).toThrow(TypeError)
  })

  it("rejects an extra field on an item inside a list response", () => {
    expect(() =>
      parsePythonAccountList([{ ...ACCOUNT, internal_metadata: { private: true } }])
    ).toThrow(TypeError)
  })

  it.each([
    ["unknown account type", { type: "investment" }],
    ["unknown role", { role: "superuser" }],
    ["unknown relation type", { relation_type: "guest" }],
    ["short currency", { currency: "EU" }],
    ["lowercase currency", { currency: "eur" }],
    ["invalid created timestamp", { created_at: "not-a-date" }],
    ["invalid updated timestamp", { updated_at: "2036-01-01" }],
    ["impossible calendar timestamp", { updated_at: "2036-02-30T00:00:00" }],
  ])("rejects %s", (_name, override) => {
    expect(() => parsePythonAccount({ ...ACCOUNT, ...override })).toThrow(TypeError)
  })
})
