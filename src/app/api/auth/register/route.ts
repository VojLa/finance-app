import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

import { createPythonAuthApi } from "@/modules/auth/server/auth-api"
import { normalizeAdapterError } from "@/modules/python-api/server/errors"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }

export async function POST(req: NextRequest) {
  try {
    const value: unknown = await req.json()
    if (typeof value !== "object" || value === null) {
      return NextResponse.json(
        { error: "Neplatné registrační údaje" },
        { status: 400, headers: NO_STORE_HEADERS }
      )
    }
    const input = value as Record<string, unknown>
    const user = await createPythonAuthApi().register({
      email: typeof input.email === "string" ? input.email : "",
      password: typeof input.password === "string" ? input.password : "",
      name: typeof input.name === "string" ? input.name : null,
    })
    return NextResponse.json(
      { id: user.id, email: user.email },
      { status: 201, headers: NO_STORE_HEADERS }
    )
  } catch (error) {
    if (error instanceof SyntaxError) {
      return NextResponse.json(
        { error: "Neplatné registrační údaje" },
        { status: 400, headers: NO_STORE_HEADERS }
      )
    }
    const mapped = normalizeAdapterError(error)
    const message =
      mapped.code === "email_already_registered"
        ? "Email již existuje"
        : mapped.status === 422
          ? "Zkontrolujte email, jméno a heslo"
          : "Registrace je dočasně nedostupná"
    return NextResponse.json(
      { error: message },
      { status: mapped.status, headers: NO_STORE_HEADERS }
    )
  }
}
