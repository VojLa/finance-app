import { getServerSession } from "next-auth"
import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

import { authOptions } from "@/lib/auth"
import { createPythonAuthApi } from "@/modules/auth/server/auth-api"
import { normalizeAdapterError } from "@/modules/python-api/server/errors"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }

export async function PUT(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) {
    return NextResponse.json(
      { error: "Přihlášení je vyžadováno" },
      { status: 401, headers: NO_STORE_HEADERS }
    )
  }

  try {
    const value: unknown = await req.json()
    const input =
      typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {}
    await createPythonAuthApi().changePassword(
      {
        userId: session.user.id,
        email: session.user.email || undefined,
      },
      {
        current_password: typeof input.currentPassword === "string" ? input.currentPassword : "",
        new_password: typeof input.newPassword === "string" ? input.newPassword : "",
      }
    )
    return NextResponse.json({ ok: true }, { headers: NO_STORE_HEADERS })
  } catch (error) {
    if (error instanceof SyntaxError) {
      return NextResponse.json(
        { error: "Neplatné údaje pro změnu hesla" },
        { status: 400, headers: NO_STORE_HEADERS }
      )
    }
    const mapped = normalizeAdapterError(error)
    const message =
      mapped.code === "current_password_invalid"
        ? "Současné heslo není správné"
        : mapped.status === 422
          ? "Nové heslo musí mít alespoň 8 znaků a nejvýše 72 bajtů"
          : "Heslo se nyní nepodařilo změnit"
    return NextResponse.json(
      { error: message },
      { status: mapped.status, headers: NO_STORE_HEADERS }
    )
  }
}
