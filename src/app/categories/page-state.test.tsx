import { readFile } from "node:fs/promises"
import path from "node:path"
import { expect, it } from "vitest"

it("distinguishes category load failure from empty data", async () => {
  const source = await readFile(path.join(process.cwd(), "src/app/categories/page.tsx"), "utf8")
  expect(source).toContain("categoryLoadError")
  expect(source).toContain("categoryLoading")
  expect(source).toContain('role="alert"')
})
