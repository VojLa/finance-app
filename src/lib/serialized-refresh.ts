export type SerializedRefreshGate = {
  running: boolean
  pending: boolean
  pendingRefresh: boolean
}

export function createSerializedRefreshGate(): SerializedRefreshGate {
  return { running: false, pending: false, pendingRefresh: false }
}

/** Runs one request at a time and coalesces overlaps into one newest follow-up. */
export async function runSerializedRefresh(
  gate: SerializedRefreshGate,
  isRefresh: boolean,
  operation: (isRefresh: boolean) => Promise<void>
): Promise<void> {
  gate.pending = true
  gate.pendingRefresh ||= isRefresh
  if (gate.running) return

  gate.running = true
  try {
    do {
      const nextIsRefresh = gate.pendingRefresh
      gate.pending = false
      gate.pendingRefresh = false
      await operation(nextIsRefresh)
    } while (gate.pending)
  } finally {
    gate.running = false
  }
}
