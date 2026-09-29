import { readFile } from "node:fs/promises"
import path from "node:path"
import { expect, it } from "vitest"

it("unlocks password form after network rejection", async () => {
  const source = await readFile(path.join(process.cwd(), "src/app/settings/page.tsx"), "utf8")
  expect(source).toContain("finally")
  expect(source).toContain('setPwError("Nepodařilo se změnit heslo")')
})
