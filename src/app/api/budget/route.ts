import { getServerSession } from "next-auth"
import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

import { authOptions } from "@/lib/auth"
import { createPythonBudgetApi } from "@/modules/budgets/server/budget-api"
import { normalizeAdapterError } from "@/modules/python-api/server/errors"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }

function identity(session: { user: { id: string; email?: string | null } }) {
  return { userId: session.user.id, email: session.user.email || undefined }
}

function unauthorized() {
  return NextResponse.json(
    { error: "Přihlášení je vyžadováno" },
    { status: 401, headers: NO_STORE_HEADERS }
  )
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new SyntaxError("Invalid JSON object")
  }
  return value as Record<string, unknown>
}

function errorResponse(error: unknown) {
  if (error instanceof SyntaxError) {
    return NextResponse.json(
      { error: "Neplatná data rozpočtu" },
      { status: 400, headers: NO_STORE_HEADERS }
    )
  }
  const mapped = normalizeAdapterError(error)
  const message =
    mapped.code === "budget_unavailable"
      ? "Rozpočet nelze sestavit z dostupných údajů"
      : mapped.code === "budget_category_invalid"
        ? "Kategorie rozpočtu není dostupná"
        : mapped.status === 422
          ? "Zkontrolujte údaje rozpočtu"
          : "Rozpočet je dočasně nedostupný"
  return NextResponse.json({ error: message }, { status: mapped.status, headers: NO_STORE_HEADERS })
}

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) return unauthorized()
  const now = new Date()
  const month = Number.parseInt(
    req.nextUrl.searchParams.get("month") ?? String(now.getMonth() + 1),
    10
  )
  const year = Number.parseInt(
    req.nextUrl.searchParams.get("year") ?? String(now.getFullYear()),
    10
  )
  try {
    const result = await createPythonBudgetApi(identity(session)).get(month, year)
    return NextResponse.json(result, { headers: NO_STORE_HEADERS })
  } catch (error) {
    return errorResponse(error)
  }
}

export async function PUT(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) return unauthorized()
  try {
    const input = record(await req.json())
    const rawItems = Array.isArray(input.items) ? input.items : []
    const items = rawItems.map((value) => {
      const item = record(value)
      return {
        categoryId: typeof item.categoryId === "string" ? item.categoryId : "",
        amount:
          typeof item.amount === "string" || typeof item.amount === "number" ? item.amount : "",
        currency: typeof item.currency === "string" ? item.currency : "CZK",
      }
    })
    const result = await createPythonBudgetApi(identity(session)).save({
      month: typeof input.month === "number" ? input.month : 0,
      year: typeof input.year === "number" ? input.year : 0,
      rollover: input.rollover === true,
      items,
    })
    return NextResponse.json(result, { headers: NO_STORE_HEADERS })
  } catch (error) {
    return errorResponse(error)
  }
}
