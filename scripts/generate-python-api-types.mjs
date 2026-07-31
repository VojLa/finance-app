import { spawnSync } from "node:child_process"
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

import openapiTS, { astToString } from "openapi-typescript"
import { format, resolveConfig } from "prettier"

const HEADER = "// This file is generated. Do not edit manually.\n\n"
const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(scriptDirectory, "..")
const backendRoot = path.join(repositoryRoot, "backend", "python")
const trackedOutput = path.join(repositoryRoot, "src", "generated", "python-api.ts")

const argumentsSet = new Set(process.argv.slice(2))
const checkOnly = argumentsSet.delete("--check")
if (argumentsSet.size > 0) {
  throw new Error(`Unsupported arguments: ${[...argumentsSet].join(", ")}`)
}

const temporaryDirectory = await mkdtemp(path.join(tmpdir(), "finance-app-python-api-"))
const schemaPath = path.join(temporaryDirectory, "openapi.json")
const temporaryOutput = path.join(temporaryDirectory, "python-api.ts")

try {
  const uvExecutable = process.platform === "win32" ? "uv.exe" : "uv"
  const exportResult = spawnSync(
    uvExecutable,
    ["run", "python", "-m", "scripts.export_openapi", "--output", schemaPath],
    {
      cwd: backendRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }
  )
  if (exportResult.error) {
    throw exportResult.error
  }
  if (exportResult.status !== 0) {
    process.stderr.write(exportResult.stderr)
    process.exitCode = exportResult.status ?? 1
  } else {
    const schema = JSON.parse(await readFile(schemaPath, "utf8"))
    const prettierConfig = await resolveConfig(trackedOutput)
    const generated = await format(`${HEADER}${astToString(await openapiTS(schema))}`, {
      ...prettierConfig,
      filepath: trackedOutput,
    })
    await writeFile(temporaryOutput, generated, { encoding: "utf8" })

    if (checkOnly) {
      const temporaryGenerated = await readFile(temporaryOutput, "utf8")
      let tracked
      try {
        tracked = await readFile(trackedOutput, "utf8")
      } catch {
        tracked = undefined
      }
      if (tracked !== temporaryGenerated) {
        process.stderr.write(
          "Generated Python API types are stale. Run npm run api:python:generate.\n"
        )
        process.exitCode = 1
      }
    } else {
      await mkdir(path.dirname(trackedOutput), { recursive: true })
      await writeFile(trackedOutput, generated, { encoding: "utf8" })
    }
  }
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true })
}
