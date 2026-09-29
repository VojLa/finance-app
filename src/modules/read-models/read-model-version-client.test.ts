import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  READ_MODEL_VERSION_INTERVAL_MS,
  ReadModelVersionPoller,
  isReadModelUpdateForScope,
} from "./read-model-version-client"

describe("ReadModelVersionPoller", () => {
  let visibilityState: DocumentVisibilityState
  let documentStub: Document

  class TestCustomEvent<T> extends Event {
    constructor(type: string, readonly detail: T) {
      super(type)
    }
  }

  beforeEach(() => {
    vi.useFakeTimers()
    visibilityState = "visible"
    const target = new EventTarget()
    Object.defineProperty(target, "visibilityState", {
      get: () => visibilityState,
    })
    documentStub = target as unknown as Document
    Object.assign(globalThis, { CustomEvent: TestCustomEvent })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("records a 204 response without dispatching an update", async () => {
    const fetchImplementation = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    const dispatchUpdate = vi.fn()
    const poller = new ReadModelVersionPoller({ fetchImplementation, dispatchUpdate, document: documentStub })

    poller.start()
    await vi.runAllTicks()

    expect(fetchImplementation).toHaveBeenCalledTimes(1)
    expect(dispatchUpdate).not.toHaveBeenCalled()
    poller.stop()
  })

  it("dispatches only a changed version and carries its scopes", async () => {
    const fetchImplementation = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ version: "first", scopes: ["portfolio"] }), { status: 200 })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ version: "second", scopes: ["dashboard"] }), { status: 200 })
      )
    const dispatchUpdate = vi.fn()
    const poller = new ReadModelVersionPoller({ fetchImplementation, dispatchUpdate, document: documentStub })

    poller.start()
    await vi.runAllTicks()
    await vi.advanceTimersByTimeAsync(READ_MODEL_VERSION_INTERVAL_MS)

    expect(dispatchUpdate).toHaveBeenCalledWith({ version: "second", scopes: ["dashboard"] })
    expect(
      isReadModelUpdateForScope(
        new TestCustomEvent("finance:read-model-updated", {
          version: "second", scopes: ["dashboard"],
        }),
        "dashboard"
      )
    ).toBe(true)
    expect(
      isReadModelUpdateForScope(
        new TestCustomEvent("finance:read-model-updated", {
          version: "second", scopes: ["dashboard"],
        }),
        "portfolio"
      )
    ).toBe(false)
    poller.stop()
  })

  it("does not poll while hidden and preserves the ten-minute request limit on return", async () => {
    const fetchImplementation = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ version: "first", scopes: [] }), { status: 200 }))
    const poller = new ReadModelVersionPoller({ fetchImplementation, document: documentStub })

    visibilityState = "hidden"
    poller.start()
    await vi.runAllTicks()
    expect(fetchImplementation).not.toHaveBeenCalled()

    visibilityState = "visible"
    documentStub.dispatchEvent(new Event("visibilitychange"))
    await vi.runAllTicks()
    expect(fetchImplementation).toHaveBeenCalledTimes(1)

    visibilityState = "hidden"
    documentStub.dispatchEvent(new Event("visibilitychange"))
    await vi.advanceTimersByTimeAsync(READ_MODEL_VERSION_INTERVAL_MS * 2)
    expect(fetchImplementation).toHaveBeenCalledTimes(1)

    visibilityState = "visible"
    documentStub.dispatchEvent(new Event("visibilitychange"))
    await vi.runAllTicks()
    expect(fetchImplementation).toHaveBeenCalledTimes(2)
    poller.stop()
  })
})
