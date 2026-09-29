import { getServerSession } from "next-auth"
import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

import { authOptions } from "@/lib/auth"
import { normalizeAdapterError } from "@/modules/python-api/server/errors"
import { createPythonTransactionApi } from "@/modules/transactions/server/transaction-api"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }
const TRANSACTION_TYPES = new Set(["income", "expense", "transfer"])

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

function text(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function optionalText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null
}

function identity(session: { user: { id: string; email?: string | null } }) {
  return { userId: session.user.id, email: session.user.email || undefined }
}

function errorResponse(error: unknown) {
  if (error instanceof SyntaxError) {
    return NextResponse.json(
      { error: "Neplatná data transakce" },
      { status: 400, headers: NO_STORE_HEADERS }
    )
  }
  const mapped = normalizeAdapterError(error)
  const message =
    mapped.code === "transaction_not_found" || mapped.code === "account_not_found"
      ? "Transakce nebo účet nebyly nalezeny"
      : mapped.code === "transaction_category_invalid"
        ? "Kategorie není pro tuto transakci dostupná"
        : mapped.status === 409
          ? "Transakci nelze bezpečně změnit"
          : mapped.status === 422
            ? "Zkontrolujte údaje transakce"
            : "Transakční služba je dočasně nedostupná"
  return NextResponse.json({ error: message }, { status: mapped.status, headers: NO_STORE_HEADERS })
}

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) return unauthorized()

  const pageValue = Number.parseInt(req.nextUrl.searchParams.get("page") ?? "1", 10)
  const rawType = req.nextUrl.searchParams.get("type") ?? undefined
  const type = rawType && TRANSACTION_TYPES.has(rawType) ? rawType : undefined
  try {
    const result = await createPythonTransactionApi(identity(session)).list({
      page: Number.isFinite(pageValue) ? Math.max(1, pageValue) : 1,
      type: type as "income" | "expense" | "transfer" | undefined,
      categoryId: req.nextUrl.searchParams.get("categoryId") || undefined,
      accountId: req.nextUrl.searchParams.get("accountId") || undefined,
      q: req.nextUrl.searchParams.get("q") || undefined,
    })
    return NextResponse.json(result, { headers: NO_STORE_HEADERS })
  } catch (error) {
    return errorResponse(error)
  }
}

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) return unauthorized()
  try {
    const input = record(await req.json())
    const result = await createPythonTransactionApi(identity(session)).create({
      date: text(input.date),
      amount:
        typeof input.amount === "number" || typeof input.amount === "string" ? input.amount : "",
      currency: text(input.currency),
      type: text(input.type) as "income" | "expense" | "transfer",
      accountId: text(input.accountId),
      description: optionalText(input.description),
      counterparty: optionalText(input.counterparty),
      note: optionalText(input.note),
      categoryId: optionalText(input.categoryId),
      idempotencyKey: text(input.idempotencyKey),
    })
    return NextResponse.json(result, { status: 201, headers: NO_STORE_HEADERS })
  } catch (error) {
    return errorResponse(error)
  }
}

export async function PATCH(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) return unauthorized()
  try {
    const input = record(await req.json())
    const transactionId = text(input.id)
    const payload: Record<string, unknown> = {
      idempotencyKey: text(input.idempotencyKey),
    }
    for (const field of [
      "date",
      "amount",
      "currency",
      "type",
      "description",
      "counterparty",
      "note",
      "categoryId",
    ]) {
      if (field in input) payload[field] = input[field]
    }
    const result = await createPythonTransactionApi(identity(session)).update(
      transactionId,
      payload as Parameters<ReturnType<typeof createPythonTransactionApi>["update"]>[1]
    )
    return NextResponse.json(result, { headers: NO_STORE_HEADERS })
  } catch (error) {
    return errorResponse(error)
  }
}

export async function DELETE(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) return unauthorized()
  try {
    const transactionId = req.nextUrl.searchParams.get("id") ?? ""
    const idempotencyKey = req.nextUrl.searchParams.get("idempotencyKey") ?? ""
    const result = await createPythonTransactionApi(identity(session)).delete(transactionId, {
      idempotencyKey,
    })
    return NextResponse.json(result, { headers: NO_STORE_HEADERS })
  } catch (error) {
    return errorResponse(error)
  }
}
