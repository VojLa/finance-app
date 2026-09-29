import { readFile } from "node:fs/promises"
import path from "node:path"
import { expect, it } from "vitest"

it("ignores obsolete transaction results and exits loading on failure", async () => {
  const source = await readFile(path.join(process.cwd(), "src/app/transactions/page.tsx"), "utf8")
  expect(source).toContain("transactionRequestId.current")
  expect(source).toContain("requestId !== transactionRequestId.current")
  expect(source).toContain("setLoadError(")
  expect(source).toContain("finally")
})
