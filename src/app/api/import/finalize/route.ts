import type { NextRequest } from "next/server"

import { handleImportFinalize } from "@/modules/imports/python/import-route"

export async function POST(request: NextRequest) {
  return handleImportFinalize(request)
}
