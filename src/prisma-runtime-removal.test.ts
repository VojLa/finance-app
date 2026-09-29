import { access, readFile, readdir } from "node:fs/promises"
import path from "node:path"
import { describe, expect, it } from "vitest"

const ROOT = process.cwd()

async function filesBelow(directory: string): Promise<string[]> {
  const result: string[] = []
  async function visit(current: string) {
    for (const entry of await readdir(path.join(ROOT, current), { withFileTypes: true })) {
      const relative = path.posix.join(current.replaceAll("\\", "/"), entry.name)
      if (entry.isDirectory()) await visit(relative)
      else result.push(relative)
    }
  }
  await visit(directory)
  return result.sort()
}

describe("R11-K Prisma runtime removal", () => {
  it("keeps production TypeScript independent of Prisma and bcrypt", async () => {
    const files = (await filesBelow("src")).filter(
      (file) => /\.(?:ts|tsx)$/.test(file) && !/\.test\.(?:ts|tsx)$/.test(file)
    )
    for (const file of files) {
      const source = await readFile(path.join(ROOT, file), "utf8")
      expect(source, file).not.toMatch(/@prisma\/client|@\/lib\/prisma|bcryptjs|PrismaClient/)
    }
  })

  it("retains only immutable SQL migration history under prisma", async () => {
    const files = await filesBelow("prisma")
    expect(files.length).toBeGreaterThan(0)
    expect(files.every((file) => file.startsWith("prisma/migrations/"))).toBe(true)
    await expect(access(path.join(ROOT, "prisma/schema.prisma"))).rejects.toThrow()
    await expect(access(path.join(ROOT, "prisma.config.ts"))).rejects.toThrow()
  })

  it("contains no Prisma generator, runtime dependency, or executable script", async () => {
    const packageJson = JSON.parse(await readFile(path.join(ROOT, "package.json"), "utf8")) as {
      scripts: Record<string, string>
      dependencies: Record<string, string>
      devDependencies: Record<string, string>
    }
    const dependencyNames = [
      ...Object.keys(packageJson.dependencies),
      ...Object.keys(packageJson.devDependencies),
    ]
    expect(dependencyNames).not.toContain("@prisma/client")
    expect(dependencyNames).not.toContain("prisma")
    expect(dependencyNames).not.toContain("bcryptjs")
    expect(Object.entries(packageJson.scripts).join("\n")).not.toMatch(/prisma|db:generate/i)

    const docker = await readFile(path.join(ROOT, "docker-compose.yml"), "utf8")
    const dockerfile = await readFile(path.join(ROOT, "Dockerfile.dev"), "utf8")
    expect(`${docker}\n${dockerfile}`).not.toMatch(/prisma|db:generate/i)
  })
})
