export function logInfo(message: string, context?: unknown): void {
  console.info(message, context ?? "")
}

export function logError(message: string, error?: unknown): void {
  console.error(message, error ?? "")
}
