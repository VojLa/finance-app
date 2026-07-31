import "server-only"

import { decodeProtectedHeader, jwtVerify } from "jose"
import { describe, expect, it } from "vitest"

import type { PythonApiConfig } from "./config"
import { issueInternalToken } from "./internal-token"

const SECRET = "test-internal-auth-secret-with-32-characters"
const CONFIG: PythonApiConfig = {
  backendUrl: "https://python.example.test",
  internalAuthSecret: SECRET,
  internalAuthIssuer: "finance-app-next",
  internalAuthAudience: "finance-app-python",
  internalAuthTokenTtlSeconds: 60,
  timeoutMs: 30000,
}
const KEY = new TextEncoder().encode(SECRET)

describe("issueInternalToken", () => {
  it("issues an HS256 JWT with the required protected header and claims", async () => {
    const token = await issueInternalToken(
      { userId: "user-123", email: "user@example.test" },
      CONFIG,
      { nowSeconds: 1_800_000_000, tokenId: "request-token-id" }
    )

    expect(decodeProtectedHeader(token)).toEqual({ alg: "HS256", typ: "JWT" })
    const { payload } = await jwtVerify(token, KEY, {
      algorithms: ["HS256"],
      issuer: "finance-app-next",
      audience: "finance-app-python",
      currentDate: new Date(1_800_000_000 * 1000),
    })
    expect(payload).toMatchObject({
      sub: "user-123",
      email: "user@example.test",
      iss: "finance-app-next",
      aud: "finance-app-python",
      iat: 1_800_000_000,
      exp: 1_800_000_060,
      jti: "request-token-id",
    })
  })

  it("omits the optional email claim when no email is present", async () => {
    const token = await issueInternalToken({ userId: "user-123" }, CONFIG, {
      nowSeconds: 1_800_000_000,
    })
    const { payload } = await jwtVerify(token, KEY, {
      currentDate: new Date(1_800_000_000 * 1000),
    })

    expect(payload).not.toHaveProperty("email")
  })

  it("does not contain roles, selectors, currency, finance, or browser credentials", async () => {
    const token = await issueInternalToken({ userId: "user-123" }, CONFIG, {
      nowSeconds: 1_800_000_000,
    })
    const { payload } = await jwtVerify(token, KEY, {
      currentDate: new Date(1_800_000_000 * 1000),
    })

    expect(payload).not.toHaveProperty("role")
    expect(payload).not.toHaveProperty("accountId")
    expect(payload).not.toHaveProperty("snapshotId")
    expect(payload).not.toHaveProperty("currency")
    expect(payload).not.toHaveProperty("value")
    expect(payload).not.toHaveProperty("nextAuthJwt")
    expect(payload).not.toHaveProperty("cookie")
    expect(payload).not.toHaveProperty("passwordHash")
  })

  it("creates a unique jti for each issuance", async () => {
    const first = await issueInternalToken({ userId: "user-123" }, CONFIG, {
      nowSeconds: 1_800_000_000,
    })
    const second = await issueInternalToken({ userId: "user-123" }, CONFIG, {
      nowSeconds: 1_800_000_000,
    })
    const firstPayload = (await jwtVerify(first, KEY)).payload
    const secondPayload = (await jwtVerify(second, KEY)).payload

    expect(firstPayload.jti).toEqual(expect.any(String))
    expect(secondPayload.jti).toEqual(expect.any(String))
    expect(firstPayload.jti).not.toBe(secondPayload.jti)
    expect(first).not.toBe(second)
  })

  it("rejects an empty subject", async () => {
    await expect(issueInternalToken({ userId: "   " }, CONFIG)).rejects.toThrow(
      "A verified server identity is required."
    )
  })
})
