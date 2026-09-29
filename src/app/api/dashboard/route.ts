import { getServerSession } from "next-auth"
import { NextResponse } from "next/server"

import { authOptions } from "@/lib/auth"
import { createPythonOperationalDashboardApi } from "@/modules/dashboard/server/operational-dashboard-api"
import { normalizeAdapterError } from "@/modules/python-api/server/errors"

const NO_STORE_HEADERS = { "Cache-Control": "no-store" }

function unauthorized() {
  return NextResponse.json(
    { error: "Přihlášení je vyžadováno" },
    { status: 401, headers: NO_STORE_HEADERS }
  )
}

export async function GET() {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) return unauthorized()
  try {
    const result = await createPythonOperationalDashboardApi({
      userId: session.user.id,
      email: session.user.email || undefined,
    }).get()
    return NextResponse.json(result, { headers: NO_STORE_HEADERS })
  } catch (error) {
    const mapped = normalizeAdapterError(error)
    const message =
      mapped.code === "budget_unavailable"
        ? "Provozní přehled nelze sestavit z dostupných údajů"
        : "Provozní přehled je dočasně nedostupný"
    return NextResponse.json(
      { error: message },
      { status: mapped.status, headers: NO_STORE_HEADERS }
    )
  }
}
