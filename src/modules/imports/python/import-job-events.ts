import type { PythonImportJob } from "./import-contract"

export const IMPORT_COMPLETED_EVENT = "finance:import-completed"
const IMPORT_JOB_CHANNEL = "finance-app.import-jobs.v1"
const TAB_ID = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`

type ImportJobBroadcast = {
  version: 1
  type: "active" | "completed"
  accountId: string
  jobId: string
  senderId: string
}

function broadcast(message: ImportJobBroadcast): void {
  if (typeof BroadcastChannel === "undefined") return
  const channel = new BroadcastChannel(IMPORT_JOB_CHANNEL)
  channel.postMessage(message)
  channel.close()
}

export function publishImportJobActive(job: PythonImportJob): void {
  broadcast({
    version: 1,
    type: "active",
    accountId: job.account_id,
    jobId: job.id,
    senderId: TAB_ID,
  })
}

export function publishImportCompleted(job: PythonImportJob): void {
  window.dispatchEvent(new Event(IMPORT_COMPLETED_EVENT))
  broadcast({
    version: 1,
    type: "completed",
    accountId: job.account_id,
    jobId: job.id,
    senderId: TAB_ID,
  })
}

function parseBroadcast(value: unknown): ImportJobBroadcast | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null
  const record = value as Record<string, unknown>
  if (
    Object.keys(record).sort().join("|") !== "accountId|jobId|senderId|type|version" ||
    record.version !== 1 ||
    !["active", "completed"].includes(record.type as string) ||
    typeof record.accountId !== "string" ||
    !record.accountId ||
    record.accountId !== record.accountId.trim() ||
    typeof record.jobId !== "string" ||
    !record.jobId ||
    record.jobId !== record.jobId.trim() ||
    typeof record.senderId !== "string" ||
    !record.senderId ||
    record.senderId.length > 100
  ) {
    return null
  }
  return record as ImportJobBroadcast
}

export function subscribeImportJobBroadcasts(callback: (message: ImportJobBroadcast) => void) {
  if (typeof BroadcastChannel === "undefined") return () => undefined
  const channel = new BroadcastChannel(IMPORT_JOB_CHANNEL)
  channel.addEventListener("message", (event) => {
    const message = parseBroadcast(event.data)
    if (message !== null && message.senderId !== TAB_ID) callback(message)
  })
  return () => channel.close()
}
