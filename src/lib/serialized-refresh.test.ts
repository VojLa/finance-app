import { describe, expect, it } from "vitest"

import { createSerializedRefreshGate, runSerializedRefresh } from "./serialized-refresh"

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe("serialized financial refresh", () => {
  it("allows one request and coalesces overlapping events into one refresh follow-up", async () => {
    const gate = createSerializedRefreshGate()
    const releases = [deferred(), deferred()]
    const calls: boolean[] = []
    let active = 0
    let maximumActive = 0
    const operation = async (isRefresh: boolean) => {
      const index = calls.length
      calls.push(isRefresh)
      active += 1
      maximumActive = Math.max(maximumActive, active)
      await releases[index]?.promise
      active -= 1
    }

    const initial = runSerializedRefresh(gate, false, operation)
    await Promise.resolve()
    await runSerializedRefresh(gate, true, operation)
    await runSerializedRefresh(gate, true, operation)
    expect(calls).toEqual([false])

    releases[0].resolve()
    await Promise.resolve()
    await Promise.resolve()
    expect(calls).toEqual([false, true])
    expect(maximumActive).toBe(1)

    releases[1].resolve()
    await initial
    expect(gate).toEqual({ running: false, pending: false, pendingRefresh: false })
  })

  it("releases the gate after a failed request", async () => {
    const gate = createSerializedRefreshGate()
    await expect(
      runSerializedRefresh(gate, true, async () => {
        throw new Error("offline")
      })
    ).rejects.toThrow("offline")

    let calls = 0
    await runSerializedRefresh(gate, true, async () => {
      calls += 1
    })
    expect(calls).toBe(1)
  })
})
