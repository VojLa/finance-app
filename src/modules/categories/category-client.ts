import type { Category, CategoryCreateRequest, CategoryUpdateRequest } from "./category-contract"

export class CategoryClientError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "CategoryClientError"
  }
}

export const CATEGORIES_PATH = "/api/categories"

async function responseJson<T>(response: Response): Promise<T> {
  const value = (await response.json()) as T | { error?: unknown }
  if (!response.ok) {
    const message =
      typeof value === "object" &&
      value !== null &&
      "error" in value &&
      typeof value.error === "string"
        ? value.error
        : "Kategorie jsou dočasně nedostupné."
    throw new CategoryClientError(message)
  }
  return value as T
}

export async function requestCategories(fetcher: typeof fetch = fetch): Promise<Category[]> {
  return responseJson<Category[]>(await fetcher(CATEGORIES_PATH, { cache: "no-store" }))
}

export async function createCategory(
  payload: CategoryCreateRequest,
  fetcher: typeof fetch = fetch
): Promise<Category> {
  return responseJson<Category>(
    await fetcher(CATEGORIES_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    })
  )
}

export async function updateCategory(
  categoryId: string,
  payload: CategoryUpdateRequest,
  fetcher: typeof fetch = fetch
): Promise<Category> {
  return responseJson<Category>(
    await fetcher(CATEGORIES_PATH, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: categoryId, ...payload }),
      cache: "no-store",
    })
  )
}

export async function deleteCategory(
  categoryId: string,
  fetcher: typeof fetch = fetch
): Promise<void> {
  await responseJson<{ ok: boolean }>(
    await fetcher(`${CATEGORIES_PATH}?id=${encodeURIComponent(categoryId)}`, {
      method: "DELETE",
      cache: "no-store",
    })
  )
}
