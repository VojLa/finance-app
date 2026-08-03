import type { NextRequest } from "next/server"

import { handleImportPost } from "@/modules/imports/python/import-route"

export function POST(request: NextRequest) {
  return handleImportPost(request, "raiffeisenbank")
}
