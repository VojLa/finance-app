import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(scriptDirectory, "..")
const argumentsList = process.argv.slice(2)
const rootArgumentIndex = argumentsList.indexOf("--root")
const root =
  rootArgumentIndex >= 0 && argumentsList[rootArgumentIndex + 1]
    ? path.resolve(argumentsList[rootArgumentIndex + 1])
    : repositoryRoot
const scanOnly = argumentsList.includes("--scan-only")

const forbiddenPackages = new Set([
  "@prisma/client",
  "bcryptjs",
  "drizzle-orm",
  "knex",
  "pg",
  "postgres",
  "prisma",
  "sequelize",
  "typeorm",
  "yahoo-finance2",
])
const forbiddenLocalImportPatterns = [
  /(?:^|\/)prisma(?:\/|$)/u,
  /(?:^|\/)(?:repositories?|services?|providers?)(?:\/|$)/u,
  /^@\/lib\/(?:db|database)(?:\/|$)/u,
]
const allowedRouteClassifications = new Map([
  ["authenticated_python_transport", "route"],
  ["delegated_authenticated_python_transport", "delegate"],
  ["local_health", "public"],
  ["nextauth_session_transport", "nextauth"],
  ["public_python_transport", "public"],
])
const allowedPresentationImports = new Set(["src/app/layout.tsx::./providers"])
const forbiddenRuntimeTokens = [
  { pattern: /\bDATABASE_URL\b/u, reason: "database access belongs to Python" },
  { pattern: /\bPrismaClient\b/u, reason: "Prisma runtime is forbidden" },
  {
    pattern: /\b(?:SELECT\s+.+\s+FROM|INSERT\s+INTO|UPDATE\s+.+\s+SET|DELETE\s+FROM)\b/iu,
    reason: "raw SQL belongs to Python",
  },
]

function normalize(filePath) {
  return filePath.split(path.sep).join("/")
}

function walk(directory) {
  if (!fs.existsSync(directory)) return []
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(directory, entry.name)
    return entry.isDirectory() ? walk(fullPath) : [fullPath]
  })
}

function isProductionSource(filePath) {
  const relative = normalize(path.relative(root, filePath))
  if (!/\.[cm]?[jt]sx?$/u.test(relative)) return false
  if (/(?:^|\/)(?:test|tests|generated)(?:\/|$)/u.test(relative)) return false
  if (/\.(?:test|spec)\.[cm]?[jt]sx?$/u.test(relative)) return false
  if (/\.d\.ts$/u.test(relative)) return false
  return true
}

function importedSpecifiers(source) {
  const specifiers = []
  const patterns = [
    /\b(?:import|export)\s+(?:[^"']*?\s+from\s+)?["']([^"']+)["']/gu,
    /\bimport\s*\(\s*["']([^"']+)["']\s*\)/gu,
    /\brequire\s*\(\s*["']([^"']+)["']\s*\)/gu,
  ]
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) specifiers.push(match[1])
  }
  return specifiers
}

function scanSources() {
  const violations = []
  for (const filePath of walk(path.join(root, "src")).filter(isProductionSource)) {
    const relative = normalize(path.relative(root, filePath))
    const source = fs.readFileSync(filePath, "utf8")
    for (const specifier of importedSpecifiers(source)) {
      if (
        forbiddenPackages.has(specifier) ||
        [...forbiddenPackages].some((name) => specifier.startsWith(`${name}/`))
      ) {
        violations.push(`${relative}: forbidden runtime dependency import '${specifier}'`)
      }
      const localSpecifier = specifier.startsWith("@/") || specifier.startsWith(".")
      if (
        localSpecifier &&
        !allowedPresentationImports.has(`${relative}::${specifier}`) &&
        forbiddenLocalImportPatterns.some((pattern) => pattern.test(specifier))
      ) {
        violations.push(`${relative}: forbidden business/data-layer import '${specifier}'`)
      }
    }
    for (const token of forbiddenRuntimeTokens) {
      if (token.pattern.test(source)) violations.push(`${relative}: ${token.reason}`)
    }
  }
  return violations
}

function exportedMethods(source) {
  const methods = new Set()
  for (const match of source.matchAll(
    /export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\b/gu
  )) {
    methods.add(match[1])
  }
  for (const match of source.matchAll(
    /\bhandler\s+as\s+(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\b/gu
  )) {
    methods.add(match[1])
  }
  return [...methods].sort()
}

function verifyPackageBoundary() {
  const violations = []
  const packagePath = path.join(root, "package.json")
  if (!fs.existsSync(packagePath)) return ["package.json: missing"]
  const packageJson = JSON.parse(fs.readFileSync(packagePath, "utf8"))
  for (const section of ["dependencies", "devDependencies", "optionalDependencies"]) {
    const dependencies = packageJson[section] ?? {}
    for (const dependency of Object.keys(dependencies)) {
      if (forbiddenPackages.has(dependency)) {
        violations.push(`package.json: forbidden ${section} entry '${dependency}'`)
      }
    }
  }
  const nextConfigPath = path.join(root, "next.config.js")
  if (fs.existsSync(nextConfigPath)) {
    const nextConfig = fs.readFileSync(nextConfigPath, "utf8")
    if (/yahoo-finance2|@prisma\/client|\bPrismaClient\b/u.test(nextConfig)) {
      violations.push("next.config.js: forbidden legacy runtime configuration")
    }
  }
  return violations
}

function verifyRoutes() {
  const violations = []
  const policyPath = path.join(root, "scripts", "typescript-boundary-policy.json")
  if (!fs.existsSync(policyPath)) return ["scripts/typescript-boundary-policy.json: missing"]
  const policy = JSON.parse(fs.readFileSync(policyPath, "utf8"))
  const policyRoutes = new Map(policy.routes.map((route) => [route.file, route]))
  const routeFiles = walk(path.join(root, "src", "app", "api"))
    .filter((filePath) => path.basename(filePath) === "route.ts")
    .map((filePath) => normalize(path.relative(root, filePath)))
    .sort()

  for (const routeFile of routeFiles) {
    const route = policyRoutes.get(routeFile)
    if (!route) {
      violations.push(`${routeFile}: active API route is not classified`)
      continue
    }
    const source = fs.readFileSync(path.join(root, routeFile), "utf8")
    const requiredSessionEnforcement = allowedRouteClassifications.get(route.classification)
    if (!requiredSessionEnforcement) {
      violations.push(`${routeFile}: unknown route classification '${route.classification}'`)
    } else if (route.sessionEnforcement !== requiredSessionEnforcement) {
      violations.push(
        `${routeFile}: '${route.classification}' requires '${requiredSessionEnforcement}' session enforcement`
      )
    }
    const actualMethods = exportedMethods(source)
    const expectedMethods = [...route.methods].sort()
    if (JSON.stringify(actualMethods) !== JSON.stringify(expectedMethods)) {
      violations.push(
        `${routeFile}: exported methods ${actualMethods.join(",")} do not match policy ${expectedMethods.join(",")}`
      )
    }
    if (route.sessionEnforcement === "route" && !source.includes("getServerSession")) {
      violations.push(`${routeFile}: authenticated route does not enforce a NextAuth session`)
    }
    if (
      route.sessionEnforcement === "delegate" &&
      !source.includes("@/modules/imports/python/import-route")
    ) {
      violations.push(
        `${routeFile}: delegated authentication is not provided by the import adapter`
      )
    }
    if (
      route.sessionEnforcement === "nextauth" &&
      (!source.includes("NextAuth") || !source.includes("authOptions"))
    ) {
      violations.push(`${routeFile}: NextAuth route does not use the configured session handler`)
    }
    if (route.sessionEnforcement === "public" && source.includes("getServerSession")) {
      violations.push(`${routeFile}: public route unexpectedly owns session enforcement`)
    }
  }
  for (const routeFile of policyRoutes.keys()) {
    if (!routeFiles.includes(routeFile)) violations.push(`${routeFile}: stale route policy entry`)
  }
  return violations
}

const violations = [
  ...scanSources(),
  ...(scanOnly ? [] : verifyPackageBoundary()),
  ...(scanOnly ? [] : verifyRoutes()),
]

if (violations.length > 0) {
  console.error("TypeScript boundary check failed:")
  for (const violation of violations) console.error(`- ${violation}`)
  process.exitCode = 1
} else {
  console.log("TypeScript boundary check passed.")
}
