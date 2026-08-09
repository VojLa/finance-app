import { access, readFile, readdir } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const ROOT = process.cwd()
const REMOVED_ROUTES = [
  "src/app/api/accounts/cash/route.ts",
  "src/app/api/accounts/[id]/shares/route.ts",
  "src/app/api/accounts/[id]/shares/[shareId]/route.ts",
  "src/app/api/import/raiffeisenbank/preview/route.ts",
]

async function productionFiles(directory: string): Promise<string[]> {
  const entries = await readdir(path.join(ROOT, directory), { withFileTypes: true })
  const files = await Promise.all(
    entries.map(async (entry) => {
      const relative = `${directory}/${entry.name}`
      if (entry.isDirectory()) return productionFiles(relative)
      if (!/\.(?:ts|tsx)$/.test(entry.name) || /\.test\.(?:ts|tsx)$/.test(entry.name)) {
        return []
      }
      return [relative]
    })
  )
  return files.flat()
}

describe("R11-D account compatibility removal", () => {
  it("removes the unused Prisma compatibility routes", async () => {
    for (const route of REMOVED_ROUTES) {
      await expect(access(path.join(ROOT, route))).rejects.toThrow()
    }
  })

  it("has no production browser or adapter consumer for the removed URLs", async () => {
    const files = await productionFiles("src")
    const combined = (
      await Promise.all(files.map((file) => readFile(path.join(ROOT, file), "utf8")))
    ).join("\n")

    expect(combined).not.toMatch(
      /\/api\/accounts\/cash|\/api\/accounts\/[^"'`]+\/shares|\/api\/import\/raiffeisenbank\/preview/
    )
  })

  it("keeps current account CRUD on Python and Python membership APIs registered", async () => {
    const accountRoute = await readFile(path.join(ROOT, "src/app/api/accounts/route.ts"), "utf8")
    const accountApi = await readFile(
      path.join(ROOT, "backend/python/app/modules/accounts/api.py"),
      "utf8"
    )
    const invitationApi = await readFile(
      path.join(ROOT, "backend/python/app/modules/accounts/invitations.py"),
      "utf8"
    )

    expect(accountRoute).toContain("listAccounts")
    expect(accountRoute).toContain("createAccount")
    expect(accountRoute).not.toMatch(/@\/lib\/prisma|accountMember|assertAccountAccess/)
    expect(accountApi).toContain('@router.get("/{account_id}/members"')
    expect(accountApi).toContain('@router.patch("/{account_id}/members/{member_id}"')
    expect(accountApi).toContain("@router.delete(")
    expect(accountApi).toContain('"/{account_id}/members/{member_id}"')
    expect(invitationApi).toContain('"/{account_id}/invites"')
    expect(invitationApi).toContain('"/invites/accept"')
  })
})
