import { afterEach, describe, expect, it, vi } from "vitest"

import type { PythonImportJob } from "./import-contract"
import {
  IMPORT_COMPLETED_EVENT,
  publishImportCompleted,
  publishImportJobActive,
  subscribeImportJobBroadcasts,
} from "./import-job-events"

const job = {
  id: "job-a",
  account_id: "account-a",
} as PythonImportJob

class FakeBroadcastChannel {
  static instances: FakeBroadcastChannel[] = []
  readonly listeners: Array<(event: MessageEvent) => void> = []
  readonly messages: unknown[] = []

  constructor(readonly name: string) {
    FakeBroadcastChannel.instances.push(this)
  }

  postMessage(value: unknown) {
    this.messages.push(value)
  }

  addEventListener(_type: "message", listener: (event: MessageEvent) => void) {
    this.listeners.push(listener)
  }

  close() {}
}

afterEach(() => {
  vi.unstubAllGlobals()
  FakeBroadcastChannel.instances = []
})

describe("cross-page import job events", () => {
  it("publishes completion locally and to other tabs without financial data", () => {
    const dispatchEvent = vi.fn()
    vi.stubGlobal("window", { dispatchEvent })
    vi.stubGlobal("BroadcastChannel", FakeBroadcastChannel)

    publishImportCompleted(job)

    expect(dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: IMPORT_COMPLETED_EVENT })
    )
    expect(FakeBroadcastChannel.instances[0]?.messages).toEqual([
      {
        version: 1,
        type: "completed",
        accountId: "account-a",
        jobId: "job-a",
        senderId: expect.any(String),
      },
    ])
  })

  it("accepts only the exact versioned active/completed broadcast shape", () => {
    vi.stubGlobal("BroadcastChannel", FakeBroadcastChannel)
    const listener = vi.fn()
    const unsubscribe = subscribeImportJobBroadcasts(listener)
    const channel = FakeBroadcastChannel.instances[0]
    const receive = channel?.listeners[0]

    receive?.({
      data: {
        version: 1,
        type: "active",
        accountId: "a",
        jobId: "j",
        senderId: "other-tab",
      },
    } as MessageEvent)
    receive?.({
      data: {
        version: 1,
        type: "completed",
        accountId: "a",
        jobId: "j",
        senderId: "other-tab",
      },
    } as MessageEvent)
    receive?.({
      data: {
        version: 1,
        type: "completed",
        accountId: "a",
        jobId: "j",
        senderId: "other-tab",
        secret: true,
      },
    } as MessageEvent)
    publishImportJobActive(job)
    unsubscribe()

    expect(listener).toHaveBeenCalledTimes(2)
    expect(FakeBroadcastChannel.instances[1]?.messages[0]).toMatchObject({ type: "active" })
  })
})
