type Json = Record<string, unknown>

const args = process.argv.slice(2)

function argValue(name: string) {
  const prefix = `--${name}=`
  const inline = args.find((arg) => arg.startsWith(prefix))
  if (inline) return inline.slice(prefix.length)

  const index = args.indexOf(`--${name}`)
  if (index >= 0) return args[index + 1]

  return undefined
}

function numberOrNull(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function diffNumber(label: string, left: unknown, right: unknown, tolerance = 0.01) {
  const leftNumber = numberOrNull(left)
  const rightNumber = numberOrNull(right)

  if (leftNumber === null || rightNumber === null) {
    return [`${label}: cannot compare (${left} vs ${right})`]
  }

  const delta = Math.abs(leftNumber - rightNumber)
  return delta <= tolerance ? [] : [`${label}: ${leftNumber} vs ${rightNumber} (delta ${delta})`]
}

async function fetchJson(url: string, cookie?: string): Promise<Json> {
  const response = await fetch(url, {
    headers: cookie ? { cookie } : {},
  })
  const text = await response.text()

  if (!response.ok) {
    throw new Error(`${url} returned ${response.status}: ${text}`)
  }

  return JSON.parse(text) as Json
}

async function main() {
  if (args.includes("--help") || args.includes("-h")) {
    console.log(`Usage:
  npm run api:compare:portfolio -- --user-id <id> [--account-id <id>] [--strict]

Environment:
  PARITY_USER_ID        User id used by the Python API while auth is temporary.
  PARITY_ACCOUNT_ID     Optional account id.
  NEXT_BACKEND_URL      Default: http://localhost:3010
  PYTHON_BACKEND_URL    Default: http://localhost:8010
  NEXT_SESSION_COOKIE   Required when comparing against authenticated Next API.
`)
    return
  }

  const userId = argValue("user-id") ?? process.env.PARITY_USER_ID
  const accountId = argValue("account-id") ?? process.env.PARITY_ACCOUNT_ID
  const nextBaseUrl = process.env.NEXT_BACKEND_URL ?? "http://localhost:3010"
  const pythonBaseUrl = process.env.PYTHON_BACKEND_URL ?? "http://localhost:8010"
  const nextCookie = process.env.NEXT_SESSION_COOKIE
  const strict = args.includes("--strict")

  if (!userId) {
    throw new Error("Missing --user-id or PARITY_USER_ID.")
  }

  const nextUrl = new URL("/api/portfolio", nextBaseUrl)
  const pythonUrl = new URL("/portfolio", pythonBaseUrl)
  pythonUrl.searchParams.set("user_id", userId)

  if (accountId) {
    nextUrl.searchParams.set("accountId", accountId)
    pythonUrl.searchParams.set("account_id", accountId)
  }

  const [nextPortfolio, pythonPortfolio] = await Promise.all([
    fetchJson(nextUrl.toString(), nextCookie),
    fetchJson(pythonUrl.toString()),
  ])

  const nextAccounts = Array.isArray(nextPortfolio.accounts) ? nextPortfolio.accounts : []
  const pythonAccounts = Array.isArray(pythonPortfolio.accounts) ? pythonPortfolio.accounts : []
  const nextHoldings = Array.isArray(nextPortfolio.holdings) ? nextPortfolio.holdings : []
  const pythonHoldings = Array.isArray(pythonPortfolio.holdings) ? pythonPortfolio.holdings : []

  const differences = [
    ...(nextAccounts.length === pythonAccounts.length
      ? []
      : [`accounts.length: ${nextAccounts.length} vs ${pythonAccounts.length}`]),
    ...(nextHoldings.length === pythonHoldings.length
      ? []
      : [`holdings.length: ${nextHoldings.length} vs ${pythonHoldings.length}`]),
    ...diffNumber("total cost", nextPortfolio.totalCostCzk, pythonPortfolio.total_cost, 1),
  ]

  console.log("Compared:")
  console.log(`  Next:   ${nextUrl}`)
  console.log(`  Python: ${pythonUrl}`)
  console.log("")

  if (differences.length === 0) {
    console.log("OK: no basic portfolio parity differences found.")
    return
  }

  console.log("Differences:")
  for (const difference of differences) console.log(`  - ${difference}`)

  if (strict) process.exitCode = 1
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error)
  process.exitCode = 1
})
