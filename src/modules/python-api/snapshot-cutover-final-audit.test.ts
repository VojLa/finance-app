import { spawnSync } from "node:child_process"
import { readFile } from "node:fs/promises"
import path from "node:path"

import { decodeProtectedHeader } from "jose"
import { describe, expect, it } from "vitest"

import type { PythonApiConfig } from "./server/config"
import { loadPythonApiConfig } from "./server/config"
import { issueInternalToken } from "./server/internal-token"

const ROOT = process.cwd()
const BACKEND_ROOT = path.join(ROOT, "backend", "python")
const HELPER = path.join("tests", "support", "verify_internal_token_cli.py")
const SECRET = "5m-final-cross-runtime-secret-32-characters"
const NOW = 1_900_000_000
const CONFIG: PythonApiConfig = {
  backendUrl: "https://python.audit.test",
  internalAuthSecret: SECRET,
  internalAuthIssuer: "finance-app-next",
  internalAuthAudience: "finance-app-python",
  internalAuthTokenTtlSeconds: 60,
  timeoutMs: 30000,
}

type VerificationResult =
  | {
      ok: true
      algorithm: "HS256"
      claims: {
        sub: string
        email: string | null
        iss: string
        aud: string | string[]
        iat: number
        exp: number
        jti: string | null
      }
    }
  | { ok: false; error: "invalid_token" }

function verifyWithPython(
  token: string,
  overrides: Partial<{
    secret: string
    issuer: string
    audience: string
    now: number
  }> = {}
): VerificationResult {
  const result = spawnSync("uv", ["run", "python", HELPER], {
    cwd: BACKEND_ROOT,
    input: JSON.stringify({
      token,
      secret: overrides.secret ?? SECRET,
      issuer: overrides.issuer ?? CONFIG.internalAuthIssuer,
      audience: overrides.audience ?? CONFIG.internalAuthAudience,
      now: overrides.now ?? NOW,
    }),
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: BACKEND_ROOT },
    timeout: 30000,
    windowsHide: true,
  })

  expect(result.status, result.stderr).toBe(0)
  expect(result.error).toBeUndefined()
  expect(result.stderr).not.toContain(token)
  expect(result.stdout).not.toContain(token)
  return JSON.parse(result.stdout) as VerificationResult
}

describe("cross-runtime internal token compatibility", () => {
  it("accepts the exact TypeScript HS256 token in the real Python verifier", async () => {
    const token = await issueInternalToken(
      { userId: "audit-user", email: "audit@example.test" },
      CONFIG,
      { nowSeconds: NOW, tokenId: "audit-jti" }
    )

    expect(decodeProtectedHeader(token)).toEqual({ alg: "HS256", typ: "JWT" })
    expect(verifyWithPython(token)).toEqual({
      ok: true,
      algorithm: "HS256",
      claims: {
        sub: "audit-user",
        email: "audit@example.test",
        iss: "finance-app-next",
        aud: "finance-app-python",
        iat: NOW,
        exp: NOW + 60,
        jti: "audit-jti",
      },
    })
  })

  it("keeps email optional across runtimes", async () => {
    const token = await issueInternalToken({ userId: "audit-user" }, CONFIG, {
      nowSeconds: NOW,
      tokenId: "audit-no-email",
    })

    const result = verifyWithPython(token)

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.claims.email).toBeNull()
      expect(result.claims.sub).toBe("audit-user")
    }
  })

  it.each([
    ["wrong secret", { secret: "wrong-cross-runtime-secret-32-characters" }],
    ["wrong issuer", { issuer: "wrong-issuer" }],
    ["wrong audience", { audience: "wrong-audience" }],
    ["expired", { now: NOW + 60 }],
  ])("rejects %s without echoing the token", async (_label, overrides) => {
    const token = await issueInternalToken({ userId: "audit-user" }, CONFIG, {
      nowSeconds: NOW,
      tokenId: "audit-rejected",
    })

    expect(verifyWithPython(token, overrides)).toEqual({
      ok: false,
      error: "invalid_token",
    })
  })

  it("rejects a future-issued token", async () => {
    const token = await issueInternalToken({ userId: "audit-user" }, CONFIG, {
      nowSeconds: NOW + 31,
      tokenId: "audit-future",
    })

    expect(verifyWithPython(token)).toEqual({
      ok: false,
      error: "invalid_token",
    })
  })

  it("rejects a malformed token through stdin with a generic safe result", () => {
    expect(verifyWithPython("malformed-token")).toEqual({
      ok: false,
      error: "invalid_token",
    })
  })
})

describe("generated OpenAPI and configuration boundary", () => {
  it("keeps every Python workflow DTO as an alias of the generated contract", async () => {
    const generated = await readFile(path.join(ROOT, "src/generated/python-api.ts"), "utf8")
    const contract = await readFile(
      path.join(ROOT, "src/modules/python-api/snapshot-workflow-contract.ts"),
      "utf8"
    )
    const generator = await readFile(
      path.join(ROOT, "scripts/generate-python-api-types.mjs"),
      "utf8"
    )

    expect(generated).toMatch(/^\/\/ This file is generated\. Do not edit manually\./)
    expect(contract).toContain('import type { components } from "@/generated/python-api"')
    for (const schema of [
      "UserSnapshotRefreshRecalculateResponse",
      "ExactPortfolioSnapshotSetRequest",
      "MultiAccountPortfolioResponse",
      "DashboardSnapshotResponse",
    ]) {
      expect(contract).toContain(`components["schemas"]["${schema}"]`)
    }
    expect(generator).toContain("mkdtemp(")
    expect(generator).toContain("tracked !== temporaryGenerated")
  })

  it("fails closed when adapter configuration is absent", () => {
    expect(() => loadPythonApiConfig({ NODE_ENV: "test" })).toThrow(
      expect.objectContaining({
        status: 503,
        code: "python_api_configuration_error",
        message: "The Python API adapter is not configured.",
      })
    )
  })

  it("keeps the public refresh summary free of manifest and sensitive fields", async () => {
    const contract = await readFile(
      path.join(ROOT, "src/modules/python-api/snapshot-workflow-contract.ts"),
      "utf8"
    )
    const summaryBlock = contract.slice(
      contract.indexOf("export type SnapshotRefreshSummary"),
      contract.indexOf("export type EmptySnapshotWorkflowResult")
    )

    expect(summaryBlock).not.toMatch(/\b(?:accounts|accountId|snapshotId)\b/)
    expect(summaryBlock).not.toMatch(
      /\b(?:token|secret|cookie|passwordHash|role|refreshMode|writeDisposition|requestId)\b/i
    )
  })
})
