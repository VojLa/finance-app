import { describe, expect, it, vi } from "vitest"

import {
  CATEGORIES_PATH,
  createCategory,
  requestCategories,
  updateCategory,
} from "./category-client"

const CATEGORY = {
  id: "category-1",
  name: "Food",
  icon: null,
  color: null,
  type: "expense" as const,
  isDefault: false,
  userId: "user-1",
  parentId: null,
  children: [],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("browser category client", () => {
  it("lists through the relative no-store route", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse([CATEGORY]))

    await expect(requestCategories(fetchMock)).resolves.toEqual([CATEGORY])
    expect(fetchMock).toHaveBeenCalledWith(CATEGORIES_PATH, { cache: "no-store" })
  })

  it("creates with generated fields and an idempotency key", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse(CATEGORY, 201))
    const payload = {
      name: "Food",
      type: "expense" as const,
      parentId: null,
      idempotencyKey: "category-command",
    }

    await createCategory(payload, fetchMock)

    expect(fetchMock).toHaveBeenCalledWith(CATEGORIES_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    })
  })

  it("updates only the explicit typed fields", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse(CATEGORY))

    await updateCategory("category-1", { name: "Groceries", parentId: null }, fetchMock)

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      id: "category-1",
      name: "Groceries",
      parentId: null,
    })
  })
})
