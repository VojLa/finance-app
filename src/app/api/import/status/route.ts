import type { NextRequest } from "next/server"

import { handleImportStatus } from "@/modules/imports/python/import-route"

export function GET(request: NextRequest) {
  return handleImportStatus(request)
}
