import crypto from "crypto"

export function createSha256Checksum(content: string | Buffer): string {
  return crypto.createHash("sha256").update(content).digest("hex")
}
