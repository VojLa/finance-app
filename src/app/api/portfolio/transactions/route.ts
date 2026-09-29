import { getServerSession } from "next-auth"
import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

import type { components } from "@/generated/python-api"
import { authOptions } from "@/lib/auth"
import { createPythonInvestmentApi } from "@/modules/investments/server/investment-api"
import { normalizeAdapterError } from "@/modules/python-api/server/errors"

type ManualInvestmentCreate = components["schemas"]["ManualInvestmentCreateRequest"]
const NO_STORE_HEADERS = { "Cache-Control": "no-store" }

function unauthorized() {
  return NextResponse.json(
    { error: "Přihlášení je vyžadováno" },
    { status: 401, headers: NO_STORE_HEADERS }
  )
}

function identity(session: { user: { id: string; email?: string | null } }) {
  return { userId: session.user.id, email: session.user.email || undefined }
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new SyntaxError("Invalid JSON object")
  }
  return value as Record<string, unknown>
}

function manualPayload(value: unknown): ManualInvestmentCreate {
  const input = record(value)
  return {
    accountId: typeof input.accountId === "string" ? input.accountId : "",
    idempotencyKey: typeof input.idempotencyKey === "string" ? input.idempotencyKey : "",
    date: typeof input.date === "string" ? input.date : "",
    type: input.type as ManualInvestmentCreate["type"],
    symbol: typeof input.symbol === "string" ? input.symbol : null,
    name: typeof input.name === "string" ? input.name : null,
    assetType: (input.assetType as ManualInvestmentCreate["assetType"]) ?? null,
    quantity:
      typeof input.quantity === "string" || typeof input.quantity === "number"
        ? input.quantity
        : null,
    pricePerUnit:
      typeof input.pricePerUnit === "string" || typeof input.pricePerUnit === "number"
        ? input.pricePerUnit
        : null,
    priceCurrency: typeof input.priceCurrency === "string" ? input.priceCurrency : null,
    totalAmount:
      typeof input.totalAmount === "string" || typeof input.totalAmount === "number"
        ? input.totalAmount
        : null,
    totalCurrency: typeof input.totalCurrency === "string" ? input.totalCurrency : null,
    fee: typeof input.fee === "string" || typeof input.fee === "number" ? input.fee : null,
    feeCurrency: typeof input.feeCurrency === "string" ? input.feeCurrency : null,
    conversionFromAmount:
      typeof input.conversionFromAmount === "string" ||
      typeof input.conversionFromAmount === "number"
        ? input.conversionFromAmount
        : null,
    conversionFromCurrency:
      typeof input.conversionFromCurrency === "string" ? input.conversionFromCurrency : null,
    conversionToAmount:
      typeof input.conversionToAmount === "string" || typeof input.conversionToAmount === "number"
        ? input.conversionToAmount
        : null,
    conversionToCurrency:
      typeof input.conversionToCurrency === "string" ? input.conversionToCurrency : null,
  }
}

function errorResponse(error: unknown) {
  if (error instanceof SyntaxError) {
    return NextResponse.json(
      { error: "Neplatná investiční operace" },
      { status: 400, headers: NO_STORE_HEADERS }
    )
  }
  const mapped = normalizeAdapterError(error)
  const message =
    mapped.code === "manual_investment_conflict"
      ? "Tento požadavek už byl použit s jinými údaji"
      : mapped.status === 403 || mapped.status === 404
        ? "Investiční účet není dostupný"
        : mapped.status === 422
          ? "Zkontrolujte údaje investiční operace"
          : "Investiční operace je dočasně nedostupná"
  return NextResponse.json({ error: message }, { status: mapped.status, headers: NO_STORE_HEADERS })
}

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) return unauthorized()
  const symbol = req.nextUrl.searchParams.get("symbol")
  if (!symbol) {
    return NextResponse.json({ error: "Chybí symbol" }, { status: 400, headers: NO_STORE_HEADERS })
  }
  try {
    const result = await createPythonInvestmentApi(identity(session)).detail(symbol)
    return NextResponse.json(result, { headers: NO_STORE_HEADERS })
  } catch (error) {
    return errorResponse(error)
  }
}

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) return unauthorized()
  try {
    const result = await createPythonInvestmentApi(identity(session)).create(
      manualPayload(await req.json())
    )
    return NextResponse.json(result, { status: 201, headers: NO_STORE_HEADERS })
  } catch (error) {
    return errorResponse(error)
  }
}
