import { execFileSync } from "node:child_process"
import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const BASE_SHA = "73a9aa668a6725e2bc7f2ba6dcd3ae1712841fc0"
const ROOT = process.cwd()

const USED_ACCOUNT_FILES = [
  "src/app/accounts/page.tsx",
  "src/app/api/accounts/route.ts",
  "src/app/api/accounts/[id]/route.ts",
  "src/app/api/accounts/[id]/archive/route.ts",
  "src/modules/accounts/account-client.ts",
  "src/modules/accounts/account-contract.ts",
  "src/modules/accounts/server/account-api.ts",
]

async function source(file: string): Promise<string> {
  return readFile(path.join(ROOT, file), "utf8")
}

function changedFiles(): string[] {
  const tracked = execFileSync("git", ["diff", "--name-only", BASE_SHA, "--"], {
    cwd: ROOT,
    encoding: "utf8",
  })
  const untracked = execFileSync("git", ["ls-files", "--others", "--exclude-standard"], {
    cwd: ROOT,
    encoding: "utf8",
  })
  return `${tracked}\n${untracked}`
    .split(/\r?\n/)
    .filter(Boolean)
    .map((value) => value.replaceAll("\\", "/"))
}

describe("account cutover static boundaries", () => {
  it("keeps forbidden account-domain dependencies out of the used production flow", async () => {
    const combined = (
      await Promise.all(USED_ACCOUNT_FILES.map(async (file) => `${file}\n${await source(file)}`))
    ).join("\n")

    expect(combined).not.toMatch(
      /@\/lib\/prisma|assertAccountAccess|getAccessibleAccountIds|prisma\.account|prisma\.accountMember|prisma\.\$transaction|\/api\/accounts\/cash|\/shares|\/api\/rates|toCzk|fmtCzk/
    )
    expect(await source("src/app/api/accounts/route.ts")).not.toMatch(
      /export\s+async\s+function\s+(?:PATCH|DELETE)/
    )
    expect(await source("src/app/api/accounts/[id]/route.ts")).not.toMatch(
      /export\s+async\s+function\s+(?:GET|POST|DELETE)/
    )
    expect(await source("src/app/api/accounts/[id]/archive/route.ts")).not.toMatch(
      /export\s+async\s+function\s+(?:GET|PATCH|DELETE)/
    )
  })

  it("derives account HTTP DTOs directly from generated OpenAPI schemas", async () => {
    const contract = await source("src/modules/accounts/account-contract.ts")

    expect(contract).toContain('components["schemas"]["AccountResponse"]')
    expect(contract).toContain('components["schemas"]["AccountCreateRequest"]')
    expect(contract).toContain('components["schemas"]["AccountUpdateRequest"]')
    expect(contract).not.toMatch(
      /type\s+PythonAccount\s*=\s*\{|type\s+CreateAccountRequest\s*=\s*\{|type\s+UpdateAccountRequest\s*=\s*\{/
    )
  })

  it("uses the shared server-only authenticated transport", async () => {
    const transport = await source("src/modules/python-api/server/transport.ts")
    const snapshotClient = await source("src/modules/python-api/server/client.ts")
    const accountApi = await source("src/modules/accounts/server/account-api.ts")

    expect(transport).toContain('import "server-only"')
    expect(transport).toContain("tokenIssuer(identity, config)")
    expect(transport).toContain('cache: "no-store"')
    expect(snapshotClient).toContain("createAuthenticatedPythonTransport(identity, options)")
    expect(accountApi).toContain("createAuthenticatedPythonTransport(identity, options)")
    expect(accountApi).toContain('import "server-only"')
  })

  it("does not change imports, Python account production, schema, migrations, or historical audits", () => {
    const changed = changedFiles()

    expect(changed).not.toContain("src/app/import/page.tsx")
    expect(changed.some((file) => file.startsWith("src/app/api/import/"))).toBe(false)
    expect(changed.some((file) => file.startsWith("backend/python/app/modules/accounts/"))).toBe(
      false
    )
    expect(changed.some((file) => file.startsWith("backend/python/app/db/"))).toBe(false)
    expect(changed.some((file) => file.startsWith("backend/python/alembic/"))).toBe(false)
    expect(changed.some((file) => file.startsWith("prisma/"))).toBe(false)
    expect(changed).not.toContain("src/generated/python-api.ts")
    expect(changed).not.toContain("ChatGPT/audits/0.1-final-acceptance.md")
    expect(changed).not.toContain("ChatGPT/audits/0.1-requirement-matrix.md")
  })
})
