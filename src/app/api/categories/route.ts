import { getServerSession } from "next-auth"
import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

import { authOptions } from "@/lib/auth"
import { createPythonCategoryApi } from "@/modules/categories/server/category-api"
import { normalizeAdapterError } from "@/modules/python-api/server/errors"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }

function identity(session: { user: { id: string; email?: string | null } }) {
  return { userId: session.user.id, email: session.user.email || undefined }
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

function unauthorized() {
  return NextResponse.json(
    { error: "Přihlášení je vyžadováno" },
    { status: 401, headers: NO_STORE_HEADERS }
  )
}

function errorResponse(error: unknown) {
  if (error instanceof SyntaxError) {
    return NextResponse.json(
      { error: "Neplatná data kategorie" },
      { status: 400, headers: NO_STORE_HEADERS }
    )
  }
  const mapped = normalizeAdapterError(error)
  const message =
    mapped.code === "category_not_found"
      ? "Kategorie nebyla nalezena nebo ji nelze upravit"
      : mapped.status === 409
        ? "Kategorie by vytvořila neplatnou hierarchii"
        : mapped.status === 422
          ? "Zkontrolujte údaje kategorie"
          : "Kategorie jsou dočasně nedostupné"
  return NextResponse.json({ error: message }, { status: mapped.status, headers: NO_STORE_HEADERS })
}

export async function GET() {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) return unauthorized()
  try {
    const result = await createPythonCategoryApi(identity(session)).list()
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
    const result = await createPythonCategoryApi(identity(session)).create({
      name: text(input.name),
      icon: optionalText(input.icon),
      color: optionalText(input.color),
      type: text(input.type) as "income" | "expense" | "both",
      parentId: optionalText(input.parentId),
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
    const categoryId = text(input.id)
    const payload: Record<string, unknown> = {}
    for (const field of ["name", "icon", "color", "type", "parentId"]) {
      if (field in input) payload[field] = input[field]
    }
    const result = await createPythonCategoryApi(identity(session)).update(
      categoryId,
      payload as Parameters<ReturnType<typeof createPythonCategoryApi>["update"]>[1]
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
    const categoryId = req.nextUrl.searchParams.get("id") ?? ""
    const result = await createPythonCategoryApi(identity(session)).delete(categoryId)
    return NextResponse.json(result, { headers: NO_STORE_HEADERS })
  } catch (error) {
    return errorResponse(error)
  }
}
