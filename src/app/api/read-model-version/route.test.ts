import { getServerSession } from "next-auth"
import { NextRequest } from "next/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { createAuthenticatedPythonTransport } from "@/modules/python-api/server/transport"
import { GET } from "./route"

vi.mock("next-auth", () => ({ getServerSession: vi.fn() }))
vi.mock("@/lib/auth", () => ({ authOptions: { providers: [] } }))
vi.mock("@/modules/python-api/server/transport", () => ({
  createAuthenticatedPythonTransport: vi.fn(),
}))

const getSession = vi.mocked(getServerSession)
const createTransport = vi.mocked(createAuthenticatedPythonTransport)
const request = (query = "") => new NextRequest(`http://next.test/api/read-model-version${query}`)

beforeEach(() => {
  vi.clearAllMocks()
  getSession.mockResolvedValue({
    user: { id: "user-1", email: "user@example.test" },
    expires: "2036-01-01",
  })
})

describe("read-model-version route", () => {
  it("requires an authenticated user", async () => {
    getSession.mockResolvedValueOnce(null)
    const response = await GET(request())
    expect(response.status).toBe(401)
    expect(createTransport).not.toHaveBeenCalled()
  })

  it("forwards an unchanged version as 204", async () => {
    const backendGet = vi.fn().mockResolvedValue({ response: new Response(null, { status: 204 }) })
    createTransport.mockReturnValue({ client: { GET: backendGet } } as never)

    const response = await GET(request("?after=opaque-token"))

    expect(response.status).toBe(204)
    expect(response.headers.get("Cache-Control")).toBe("no-store")
    expect(backendGet).toHaveBeenCalledWith("/api/v1/read-model-version", {
      params: { query: { after: "opaque-token" } },
    })
  })

  it("returns only the Python version payload", async () => {
    const backendGet = vi.fn().mockResolvedValue({
      response: new Response(null, { status: 200 }),
      data: { version: "opaque-token", scopes: ["portfolio", "dashboard"] },
    })
    createTransport.mockReturnValue({ client: { GET: backendGet } } as never)

    const response = await GET(request())

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({
      version: "opaque-token",
      scopes: ["portfolio", "dashboard"],
    })
  })

  it("rejects malformed query input before forwarding it", async () => {
    const response = await GET(request("?after=&other=value"))
    expect(response.status).toBe(422)
    expect(createTransport).not.toHaveBeenCalled()
  })
})
