import { spawnSync } from "node:child_process"
import process from "node:process"

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    shell: process.platform === "win32",
    ...options,
  })
  if (result.error) {
    throw result.error
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1)
  }
}

if (process.env.CI !== "true" || process.env.ALLOW_FROZEN_PRISMA_ARCHIVE_DEPLOY !== "1") {
  console.error(
    "Frozen Prisma archive deployment is restricted to the explicit CI verification path."
  )
  process.exit(1)
}

if (!process.env.DATABASE_URL) {
  console.error("DATABASE_URL is required for frozen Prisma archive verification.")
  process.exit(2)
}

run("uv", ["run", "python", "scripts/database_migrate.py", "archive-target-check"], {
  cwd: "backend/python",
})
run("npx", ["prisma", "migrate", "deploy"])
