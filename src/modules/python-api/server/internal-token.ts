import "server-only"

import { randomUUID } from "node:crypto"

import { SignJWT } from "jose"

import type { PythonApiConfig } from "./config"

export type ServerIdentity = {
  userId: string
  email?: string
}

export type InternalTokenOptions = {
  nowSeconds?: number
  tokenId?: string
}

export async function issueInternalToken(
  identity: ServerIdentity,
  config: PythonApiConfig,
  options: InternalTokenOptions = {}
): Promise<string> {
  if (identity.userId.trim().length === 0) {
    throw new TypeError("A verified server identity is required.")
  }

  const issuedAt = options.nowSeconds ?? Math.floor(Date.now() / 1000)
  const payload = identity.email ? { email: identity.email } : {}
  return new SignJWT(payload)
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .setSubject(identity.userId)
    .setIssuer(config.internalAuthIssuer)
    .setAudience(config.internalAuthAudience)
    .setIssuedAt(issuedAt)
    .setExpirationTime(issuedAt + config.internalAuthTokenTtlSeconds)
    .setJti(options.tokenId ?? randomUUID())
    .sign(new TextEncoder().encode(config.internalAuthSecret))
}
