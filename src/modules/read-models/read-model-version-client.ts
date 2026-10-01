"use client"

import { useEffect } from "react"

export const READ_MODEL_VERSION_PATH = "/api/read-model-version"
export const READ_MODEL_VERSION_INTERVAL_MS = 10 * 60 * 1000
export const READ_MODEL_UPDATED_EVENT = "finance:read-model-updated"

export type ReadModelUpdateDetail = Readonly<{
  version: string
  scopes: readonly string[]
}>

type FetchImplementation = typeof fetch
type TimeoutHandle = ReturnType<typeof globalThis.setTimeout>
type ScheduleTimeout = (handler: () => void, delay: number) => TimeoutHandle
type CancelTimeout = (handle: TimeoutHandle) => void

type VersionPollerDependencies = Readonly<{
  fetchImplementation?: FetchImplementation
  now?: () => number
  document?: Document
  dispatchUpdate?: (detail: ReadModelUpdateDetail) => void
  setTimeout?: ScheduleTimeout
  clearTimeout?: CancelTimeout
}>

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isVersionUpdate(value: unknown): value is { version: string; scopes: string[] } {
  return (
    isRecord(value) &&
    typeof value.version === "string" &&
    value.version.length > 0 &&
    Array.isArray(value.scopes) &&
    value.scopes.every((scope) => typeof scope === "string")
  )
}

export function isReadModelUpdateForScope(event: Event, scope: string): boolean {
  if (typeof CustomEvent === "undefined") return false
  if (!(event instanceof CustomEvent) || !isRecord(event.detail)) return false
  return Array.isArray(event.detail.scopes) && event.detail.scopes.includes(scope)
}

export class ReadModelVersionPoller {
  private readonly fetchImplementation: FetchImplementation
  private readonly now: () => number
  private readonly document: Document
  private readonly dispatchUpdate: (detail: ReadModelUpdateDetail) => void
  private readonly scheduleTimeout: ScheduleTimeout
  private readonly cancelTimeout: CancelTimeout
  private version: string | null = null
  private lastRequestAt: number | null = null
  private timeout: TimeoutHandle | null = null
  private started = false
  private inFlight = false

  constructor(dependencies: VersionPollerDependencies = {}) {
    this.fetchImplementation = dependencies.fetchImplementation ?? globalThis.fetch
    this.now = dependencies.now ?? Date.now
    this.document = dependencies.document ?? globalThis.document
    this.dispatchUpdate =
      dependencies.dispatchUpdate ??
      ((detail) => window.dispatchEvent(new CustomEvent(READ_MODEL_UPDATED_EVENT, { detail })))
    const timerHost = globalThis
    this.scheduleTimeout =
      dependencies.setTimeout === undefined
        ? (handler, delay) => timerHost.setTimeout(handler, delay)
        : (handler, delay) =>
            Reflect.apply(dependencies.setTimeout as ScheduleTimeout, timerHost, [handler, delay])
    this.cancelTimeout =
      dependencies.clearTimeout === undefined
        ? (handle) => timerHost.clearTimeout(handle)
        : (handle) => Reflect.apply(dependencies.clearTimeout as CancelTimeout, timerHost, [handle])
  }

  start() {
    if (this.started) return
    this.started = true
    this.document.addEventListener("visibilitychange", this.onVisibilityChange)
    this.pollWhenDue()
  }

  stop() {
    this.started = false
    this.document.removeEventListener("visibilitychange", this.onVisibilityChange)
    if (this.timeout !== null) this.cancelTimeout(this.timeout)
    this.timeout = null
  }

  private onVisibilityChange = () => {
    if (this.document.visibilityState !== "visible") {
      if (this.timeout !== null) this.cancelTimeout(this.timeout)
      this.timeout = null
      return
    }
    this.pollWhenDue()
  }

  private pollWhenDue() {
    if (!this.started || this.document.visibilityState !== "visible" || this.inFlight) return

    const elapsed =
      this.lastRequestAt === null ? READ_MODEL_VERSION_INTERVAL_MS : this.now() - this.lastRequestAt
    if (elapsed < READ_MODEL_VERSION_INTERVAL_MS) {
      this.schedule(READ_MODEL_VERSION_INTERVAL_MS - elapsed)
      return
    }

    this.lastRequestAt = this.now()
    this.inFlight = true
    const after = this.version === null ? "" : `?after=${encodeURIComponent(this.version)}`
    void this.fetchImplementation(`${READ_MODEL_VERSION_PATH}${after}`, {
      method: "GET",
      cache: "no-store",
    })
      .then(async (response) => {
        if (response.status === 204 || !response.ok) return
        const payload: unknown = await response.json()
        if (!isVersionUpdate(payload)) return

        const previousVersion = this.version
        this.version = payload.version
        if (previousVersion !== null && previousVersion !== payload.version) {
          this.dispatchUpdate({ version: payload.version, scopes: payload.scopes })
        }
      })
      .catch(() => undefined)
      .finally(() => {
        this.inFlight = false
        this.schedule(READ_MODEL_VERSION_INTERVAL_MS)
      })
  }

  private schedule(delay: number) {
    if (!this.started || this.document.visibilityState !== "visible") return
    if (this.timeout !== null) this.cancelTimeout(this.timeout)
    this.timeout = this.scheduleTimeout(() => {
      this.timeout = null
      this.pollWhenDue()
    }, delay)
  }
}

export function ReadModelVersionMonitor() {
  useEffect(() => {
    const poller = new ReadModelVersionPoller()
    poller.start()
    return () => poller.stop()
  }, [])

  return null
}
