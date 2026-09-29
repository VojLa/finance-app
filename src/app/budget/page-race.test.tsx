import { readFile } from "node:fs/promises"
import path from "node:path"
import { expect, it } from "vitest"

it("keeps prior budget while a newer month loads and ignores obsolete responses", async () => {
  const source = await readFile(path.join(process.cwd(), "src/app/budget/page.tsx"), "utf8")
  expect(source).toContain("budgetRequestId.current")
  expect(source).toContain("requestId !== budgetRequestId.current")
  expect(source).toContain("lastLoadedPeriod")
  expect(source).toContain("finally")
})
