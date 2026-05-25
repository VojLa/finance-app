import type { ParseIssue, ParseResult } from "./parsers/shared/result"

export interface ImportResult {
  imported: number
  skipped: number
  duplicates: number
  parsed: number
  rowsTotal: number
  duplicateFile?: boolean
  parseIssues?: ParseIssue[]
  warnings: { symbol: string; quantity: number }[]
}

interface RunImportOptions<T extends { externalId?: string | null }> {
  parseResult: ParseResult<T>
  accountId: string
  importBatchId: string
  fetchExistingIds: (accountId: string) => Promise<Array<{ externalId: string | null }>>
  saveRows: (rows: T[], importBatchId: string) => Promise<void>
  postProcess?: () => Promise<{ warnings?: { symbol: string; quantity: number }[] } | void>
}

export async function runImport<T extends { externalId?: string | null }>({
  parseResult,
  accountId,
  importBatchId,
  fetchExistingIds,
  saveRows,
  postProcess,
}: RunImportOptions<T>): Promise<ImportResult> {
  const { rows, rowsTotal, issues } = parseResult
  const existing = await fetchExistingIds(accountId)
  const existingIds = new Set(existing.map((t) => t.externalId))

  const newRows = rows.filter((r) => !r.externalId || !existingIds.has(r.externalId))

  let warnings: { symbol: string; quantity: number }[] = []
  if (newRows.length > 0) {
    await saveRows(newRows, importBatchId)
    const postResult = await postProcess?.()
    if (postResult && "warnings" in postResult) {
      warnings = postResult.warnings ?? []
    }
  }

  return {
    imported: newRows.length,
    skipped: rows.length - newRows.length,
    duplicates: rows.length - newRows.length,
    parsed: rows.length,
    rowsTotal,
    parseIssues: issues,
    warnings,
  }
}
