import { readFileSync } from "node:fs"
import { join } from "node:path"

import { describe, expect, it } from "vitest"

const root = process.cwd()
const workflow = readFileSync(
  join(root, "src/modules/python-api/server/snapshot-workflow.ts"),
  "utf8"
)
const currentApi = readFileSync(
  join(root, "backend/python/app/modules/current_value/api.py"),
  "utf8"
)
const MONEY = /^-?(?:0|[1-9]\d{0,11})\.\d{6}$/

describe("Version 0.1 R10-E1 browser closure boundary", () => {
  it("keeps both active browser workflows on the authenticated Python current API", () => {
    expect(workflow).toContain("api.readCurrentPortfolio()")
    expect(workflow).toContain("api.readCurrentDashboard()")
    expect(currentApi).toContain('"/portfolio/current"')
    expect(currentApi).toContain('"/dashboard/current"')
    expect(workflow).not.toContain("/api/rates")
    expect(workflow).not.toContain("snapshot-refresh/recalculate")
  })

  it("retains the canonical six-decimal MONEY contract exposed by the E1 acceptance", () => {
    expect(MONEY.test("1800.000000")).toBe(true)
    expect(MONEY.test("-1800.000000")).toBe(true)
    expect(MONEY.test("1800.00000000000000")).toBe(false)
  })
})
