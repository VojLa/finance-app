import { spawnSync } from "node:child_process"
import { mkdtemp, readFile, rm } from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import { randomUUID } from "node:crypto"

import { decodeJwt } from "jose"
import { getServerSession } from "next-auth"
import { NextRequest } from "next/server"
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest"

import * as importRoute from "@/app/api/import/route"
import { requestImport } from "./import-client"
import type { PythonImportSource } from "./import-contract"

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}))

vi.mock("@/lib/auth", () => ({
  authOptions: { providers: [] },
}))

const DATABASE_URL = process.env.DATABASE_URL
const ROOT = process.cwd()
const BACKEND_ROOT = path.join(ROOT, "backend", "python")
const HELPER = path.join(BACKEND_ROOT, "tests", "support", "import_http_bridge_cli.py")
const SECRET = "r4-postgresql-internal-auth-secret-32-characters"

type BridgeResponse = Record<string, unknown> & { ok: boolean }

function bridge(input: Record<string, unknown>): BridgeResponse {
  const result = spawnSync("uv", ["run", "python", HELPER], {
    cwd: BACKEND_ROOT,
    env: { ...process.env, PYTHONPATH: BACKEND_ROOT },
    input: JSON.stringify(input),
    encoding: "utf8",
    windowsHide: true,
    maxBuffer: 10 * 1024 * 1024,
  })
  if (result.status !== 0) {
    throw new Error(`Python bridge failed with status ${result.status}.`)
  }
  const line = result.stdout.trim().split(/\r?\n/).at(-1)
  if (!line) throw new Error("Python bridge returned no result.")
  const value = JSON.parse(line) as BridgeResponse
  if (!value.ok) throw new Error(`Python bridge rejected ${String(value.error)}.`)
  return value
}

describe.skipIf(!DATABASE_URL)("R4 browser-to-FastAPI PostgreSQL acceptance", () => {
  const runId = randomUUID()
  const userId = `r4-user-${runId}`
  const foreignUserId = `r4-foreign-user-${runId}`
  const accounts = {
    raiffeisenbank: `r4-bank-${runId}`,
    trading212: `r4-broker-${runId}`,
    anycoin: `r4-exchange-${runId}`,
    foreign: `r4-foreign-account-${runId}`,
  }
  let storageRoot = ""
  const tokenSubjects: string[] = []
  const tokenJtis: string[] = []
  const uploadedBodies: Uint8Array[] = []

  beforeAll(async () => {
    storageRoot = await mkdtemp(path.join(os.tmpdir(), "finance-app-r4-"))
    vi.stubEnv("PYTHON_BACKEND_URL", "http://python.r4.test")
    vi.stubEnv("INTERNAL_AUTH_SECRET", SECRET)
    vi.stubEnv("INTERNAL_AUTH_ISSUER", "finance-app-next")
    vi.stubEnv("INTERNAL_AUTH_AUDIENCE", "finance-app-python")
    vi.stubEnv("INTERNAL_AUTH_TOKEN_TTL_SECONDS", "60")
    vi.stubEnv("PYTHON_API_TIMEOUT_MS", "120000")
    vi.mocked(getServerSession).mockResolvedValue({
      user: { id: userId, email: `${userId}@example.test` },
      expires: "2036-01-01",
    })
    bridge({
      action: "seed",
      database_url: DATABASE_URL,
      user_id: userId,
      foreign_user_id: foreignUserId,
      accounts: [
        { id: accounts.raiffeisenbank, type: "bank", currency: "CZK" },
        { id: accounts.trading212, type: "broker", currency: "EUR" },
        { id: accounts.anycoin, type: "exchange", currency: "EUR" },
        { id: accounts.foreign, type: "bank", currency: "CZK", foreign: true },
      ],
    })

    const serverFetch = vi.fn<typeof fetch>(async (input, init) => {
      const request = new Request(input, init)
      const authorization = request.headers.get("Authorization")
      const token = authorization?.replace("Bearer ", "")
      const claims = decodeJwt(token ?? "")
      tokenSubjects.push(String(claims.sub))
      tokenJtis.push(String(claims.jti))
      const body = new Uint8Array(await request.arrayBuffer())
      if (request.method === "PUT") uploadedBodies.push(body)
      const result = bridge({
        action: "http",
        database_url: DATABASE_URL,
        storage_root: storageRoot,
        secret: SECRET,
        method: request.method,
        path: `${new URL(request.url).pathname}${new URL(request.url).search}`,
        headers: {
          Authorization: authorization,
          Accept: request.headers.get("Accept"),
          "Content-Type": request.headers.get("Content-Type"),
        },
        body_base64: Buffer.from(body).toString("base64"),
      })
      return new Response(JSON.stringify(result.body), {
        status: result.status as number,
        headers: { "Content-Type": String(result.content_type) },
      })
    })
    vi.stubGlobal("fetch", serverFetch)
  }, 120000)

  afterAll(async () => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
    vi.clearAllMocks()
    if (storageRoot) await rm(storageRoot, { recursive: true, force: true })
  })

  async function browserImport(accountId: string, source: PythonImportSource, fixturePath: string) {
    const bytes = new Uint8Array(await readFile(path.join(ROOT, fixturePath)))
    const browserFetch = vi.fn<typeof fetch>(async (input, init) => {
      const url =
        typeof input === "string"
          ? new URL(input, "http://next.r4.test")
          : input instanceof URL
            ? input
            : new URL(input.url)
      return importRoute.POST(new NextRequest(new Request(url, init)))
    })
    const result = await requestImport(
      accountId,
      source,
      [new File([bytes], path.basename(fixturePath), { type: "text/csv" })],
      browserFetch
    )
    expect(browserFetch).toHaveBeenCalledTimes(1)
    expect(result.files).toHaveLength(1)
    expect(result.files[0]).toMatchObject({
      filename: path.basename(fixturePath),
      batchId: expect.any(String),
      status: expect.stringMatching(/completed/),
      rowsImported: expect.any(Number),
    })
    expect(JSON.stringify(result)).not.toMatch(
      /Authorization|Cookie|token|password|request_id|raw_import_row|backend/
    )
    return { bytes, result }
  }

  it.each([
    [
      "raiffeisenbank",
      "backend/python/tests/fixtures/imports/raiffeisenbank/account_statement.csv",
      "transactions",
    ],
    ["trading212", "backend/python/tests/fixtures/imports/trading212/activity.csv", "events"],
    ["anycoin", "backend/python/tests/fixtures/imports/anycoin/history.csv", "events"],
  ] as const)(
    "persists %s fixture evidence through the public staged API",
    async (source, fixture, canonicalKind) => {
      const accountId = accounts[source]
      const { bytes } = await browserImport(accountId, source, fixture)
      const persisted = bridge({
        action: "inspect",
        database_url: DATABASE_URL,
        account_id: accountId,
      })

      expect(persisted.batches).toBe(1)
      expect(Number(persisted.rows)).toBeGreaterThan(0)
      expect(Number(persisted[canonicalKind])).toBeGreaterThan(0)
      expect(
        uploadedBodies.some((uploaded) => Buffer.from(uploaded).equals(Buffer.from(bytes)))
      ).toBe(true)
    },
    180000
  )

  it("enforces foreign-account nondisclosure through Python authorization", async () => {
    const fixture = await readFile(
      path.join(ROOT, "backend/python/tests/fixtures/imports/raiffeisenbank/account_statement.csv")
    )
    const browserFetch = vi.fn<typeof fetch>(async (input, init) => {
      const url =
        typeof input === "string"
          ? new URL(input, "http://next.r4.test")
          : input instanceof URL
            ? input
            : new URL(input.url)
      return importRoute.POST(new NextRequest(new Request(url, init)))
    })

    await expect(
      requestImport(
        accounts.foreign,
        "raiffeisenbank",
        [new File([fixture], "foreign.csv")],
        browserFetch
      )
    ).rejects.toMatchObject({
      status: 404,
      code: expect.any(String),
      message: expect.any(String),
    })
    expect(browserFetch).toHaveBeenCalledTimes(1)
    const persisted = bridge({
      action: "inspect",
      database_url: DATABASE_URL,
      account_id: accounts.foreign,
    })
    expect(persisted.batches).toBe(0)
    expect(persisted.rows).toBe(0)
  }, 120000)

  it("uses the exact session subject and a fresh token for every Python request", () => {
    expect(tokenSubjects).toHaveLength(25)
    expect(new Set(tokenSubjects)).toEqual(new Set([userId]))
    expect(tokenJtis).toHaveLength(25)
    expect(new Set(tokenJtis).size).toBe(25)
  })
})
