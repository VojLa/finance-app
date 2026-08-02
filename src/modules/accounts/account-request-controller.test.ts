import { describe, expect, it, vi } from "vitest"

import { createAccountRequestController } from "./account-request-controller"

describe("account page request controller", () => {
  it("deduplicates the Strict Mode initial effect and performs one request per explicit reload", async () => {
    const request = vi.fn(async () => [])
    const controller = createAccountRequestController(request)

    await controller.initial()
    await controller.initial()
    expect(request).toHaveBeenCalledTimes(1)

    await controller.reload()
    expect(request).toHaveBeenCalledTimes(2)
    await controller.reload()
    expect(request).toHaveBeenCalledTimes(3)
    await controller.reload()
    expect(request).toHaveBeenCalledTimes(4)
  })
})
