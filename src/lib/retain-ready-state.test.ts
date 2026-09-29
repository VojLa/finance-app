import { describe, expect, it } from "vitest"

import { resolveSnapshotPublication } from "./retain-ready-state"

type State =
  | { status: "loading" }
  | { status: "ready"; snapshotId: string }
  | { status: "error"; message: string }

const ready: Extract<State, { status: "ready" }> = { status: "ready", snapshotId: "snapshot-a" }

describe("atomic snapshot publication state", () => {
  it("retains the last ready snapshot and exposes only a nonblocking warning on refresh failure", () => {
    expect(
      resolveSnapshotPublication<State>(
        { status: "error", message: "Refresh unavailable." },
        ready,
        true
      )
    ).toEqual({ state: ready, lastReady: ready, warning: "Refresh unavailable." })
    expect(resolveSnapshotPublication<State>({ status: "loading" }, ready, true)).toEqual({
      state: ready,
      lastReady: ready,
      warning: "Snapshot se ještě připravuje.",
    })
  })

  it("does not hide an initial-load failure and replaces the retained snapshot only with ready data", () => {
    const failed = { status: "error", message: "Initial unavailable." } as const
    expect(resolveSnapshotPublication<State>(failed, null, false)).toEqual({
      state: failed,
      lastReady: null,
      warning: null,
    })

    const newer = { status: "ready", snapshotId: "snapshot-b" } as const
    expect(resolveSnapshotPublication<State>(newer, ready, true)).toEqual({
      state: newer,
      lastReady: newer,
      warning: null,
    })
  })
})
