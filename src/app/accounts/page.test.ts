import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

import { toAccountPageModel } from "@/modules/accounts/account-contract"

const PAGE_PATH = path.join(process.cwd(), "src/app/accounts/page.tsx")

describe("account page Python cutover", () => {
  it("loads account metadata once through the browser account client", async () => {
    const source = await readFile(PAGE_PATH, "utf8")

    expect(source).toContain("useEffect(() =>")
    expect(source).toContain("void loadAccounts()")
    expect(source).toContain("await requestAccounts()")
    expect(source).toContain('setPageState({ status: "loading" })')
    expect(source).toContain('status: "ready"')
    expect(source).toContain('status: "error"')
  })

  it("uses generated create/update/archive client operations with explicit loading states", async () => {
    const source = await readFile(PAGE_PATH, "utf8")

    expect(source).toContain("await requestCreateAccount(payload)")
    expect(source).toContain("await requestUpdateAccount(accountId, payload)")
    expect(source).toContain("await requestArchiveAccount(account.id)")
    expect(source).toContain('action: "create"')
    expect(source).toContain('action: "update"')
    expect(source).toContain('action: "archive"')
    expect(source).toContain("await loadAccounts()")
  })

  it("keeps account type readonly during edit and omits it from PATCH", async () => {
    const source = await readFile(PAGE_PATH, "utf8")
    const updatePayload = source.slice(
      source.indexOf("const payload: UpdateAccountRequest"),
      source.indexOf("try {", source.indexOf("const payload: UpdateAccountRequest"))
    )

    expect(updatePayload).toContain("name: editForm.name")
    expect(updatePayload).toContain("currency: editForm.currency")
    expect(updatePayload).not.toContain("type:")
    expect(source).toContain("ACCOUNT_TYPE_LABELS[account.type]")
    expect(source).not.toContain("setEditForm((current) => ({ ...current, type:")
  })

  it("archives non-destructively with the required confirmation", async () => {
    const source = await readFile(PAGE_PATH, "utf8")

    expect(source).toContain("Archivovat účet")
    expect(source).toContain("Účet bude archivován. Jeho finanční data nebudou smazána.")
    expect(source).not.toContain('"DELETE"')
    expect(source).not.toContain("Smazat účet")
  })

  it("has no legacy cash, sharing, Prisma, FX, retry, or financial calculation path", async () => {
    const source = await readFile(PAGE_PATH, "utf8")

    expect(source).not.toMatch(
      /@\/lib\/prisma|assertAccountAccess|getAccessibleAccountIds|\/api\/accounts\/cash|\/shares|\/api\/rates|toCzk|fmtCzk|AccountCash|AccountBalance/
    )
    expect(source).not.toMatch(/setTimeout|retry|fallback|parseFloat|Math\.round|toFixed/)
    expect(source).not.toContain("fetch(")
  })

  it("renders explicit empty and safe error states without raw internals", async () => {
    const source = await readFile(PAGE_PATH, "utf8")

    expect(source).toContain('pageState.status === "ready" && accounts.length === 0')
    expect(source).toContain('pageState.status === "error"')
    expect(source).toContain("{pageState.message}")
    expect(source).not.toMatch(/request_id|traceback|backendUrl|Authorization|internal token/)
  })

  it("maps only structural generated account fields into the page model", () => {
    const account = {
      id: "account-1",
      name: "Broker",
      type: "broker" as const,
      currency: "EUR",
      color: null,
      notes: "Long term",
      role: "owner" as const,
      relation_type: "owner" as const,
      is_archived: false,
      created_at: "2036-01-01T00:00:00",
      updated_at: "2036-01-01T00:00:00",
    }

    expect(toAccountPageModel(account)).toEqual({
      id: "account-1",
      name: "Broker",
      type: "broker",
      currency: "EUR",
      color: null,
      notes: "Long term",
      role: "owner",
      relationType: "owner",
      isArchived: false,
    })
  })
})
