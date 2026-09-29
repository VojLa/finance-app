type SnapshotLoadState =
  | { status: "loading" }
  | { status: "ready" }
  | { status: "error"; message: string }

export type SnapshotPublicationDecision<State extends SnapshotLoadState> = Readonly<{
  state: State
  lastReady: Extract<State, { status: "ready" }> | null
  warning: string | null
}>

/** Keeps the last atomically published snapshot visible during a failed refresh. */
export function resolveSnapshotPublication<State extends SnapshotLoadState>(
  next: State,
  lastReady: Extract<State, { status: "ready" }> | null,
  isRefresh: boolean
): SnapshotPublicationDecision<State> {
  if (next.status === "ready") {
    return {
      state: next,
      lastReady: next as Extract<State, { status: "ready" }>,
      warning: null,
    }
  }
  if (isRefresh && lastReady !== null) {
    return {
      state: lastReady as State,
      lastReady,
      warning: next.status === "error" ? next.message : "Snapshot se ještě připravuje.",
    }
  }
  return { state: next, lastReady, warning: null }
}
