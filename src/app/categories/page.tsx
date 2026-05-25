"use client"

import { useEffect, useState } from "react"

type SubCategory = {
  id: string
  name: string
  icon: string | null
  color: string | null
  type: string
  isDefault: boolean
  userId: string | null
}

type Category = SubCategory & {
  parentId: string | null
  children: SubCategory[]
}

type CatForm = {
  name: string
  icon: string
  color: string
  type: string
  parentId: string
}

const CATEGORY_TYPES = [
  { value: "expense", label: "Výdaj" },
  { value: "income", label: "Příjem" },
  { value: "both", label: "Oboje" },
]

const TYPE_LABEL: Record<string, string> = { expense: "Výdaj", income: "Příjem", both: "Oboje" }

const COLORS = [
  "#ef4444",
  "#f97316",
  "#f59e0b",
  "#16a34a",
  "#10b981",
  "#0891b2",
  "#3b82f6",
  "#6366f1",
  "#8b5cf6",
  "#ec4899",
  "#64748b",
]

function emptyForm(): CatForm {
  return { name: "", icon: "", color: "#3b82f6", type: "expense", parentId: "" }
}

// ─── CatFormFields ────────────────────────────────────────────────────────────

function CatFormFields({
  form,
  parentOptions,
  onChange,
}: {
  form: CatForm
  parentOptions: Category[]
  onChange: (f: CatForm) => void
}) {
  function set(k: keyof CatForm) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      onChange({ ...form, [k]: e.target.value })
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div className="sm:col-span-2">
        <label className="block text-sm font-medium text-gray-700 mb-1">Název *</label>
        <input
          type="text"
          value={form.name}
          onChange={set("name")}
          required
          placeholder="Název kategorie"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Emoji / ikona</label>
        <input
          type="text"
          value={form.icon}
          onChange={set("icon")}
          placeholder="🛒"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Typ *</label>
        <select
          value={form.type}
          onChange={set("type")}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {CATEGORY_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>
      <div className="sm:col-span-2">
        <label className="block text-sm font-medium text-gray-700 mb-1">Barva</label>
        <div className="flex gap-2 flex-wrap mt-1">
          {COLORS.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => onChange({ ...form, color: c })}
              className={`w-7 h-7 rounded-full border-2 transition-all ${
                form.color === c
                  ? "border-gray-900 scale-110"
                  : "border-transparent hover:scale-105"
              }`}
              style={{ backgroundColor: c }}
            />
          ))}
        </div>
      </div>
      <div className="sm:col-span-2">
        <label className="block text-sm font-medium text-gray-700 mb-1">Nadkategorie</label>
        <select
          value={form.parentId}
          onChange={set("parentId")}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">— žádná (top-level) —</option>
          {parentOptions.map((c) => (
            <option key={c.id} value={c.id}>
              {c.icon} {c.name}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CategoriesPage() {
  const [categories, setCategories] = useState<Category[]>([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<CatForm>(emptyForm())
  const [formLoading, setFormLoading] = useState(false)
  const [formError, setFormError] = useState("")
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<CatForm>(emptyForm())
  const [editLoading, setEditLoading] = useState(false)
  const [editError, setEditError] = useState("")

  async function load() {
    const res = await fetch("/api/categories")
    if (res.ok) setCategories(await res.json())
  }

  useEffect(() => {
    load()
  }, [])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormLoading(true)
    setFormError("")
    const res = await fetch("/api/categories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: form.name,
        icon: form.icon || null,
        color: form.color || null,
        type: form.type,
        parentId: form.parentId || null,
      }),
    })
    setFormLoading(false)
    if (!res.ok) {
      const d = await res.json()
      setFormError(d.error)
    } else {
      setShowForm(false)
      setForm(emptyForm())
      load()
    }
  }

  function startEdit(cat: Category | SubCategory, parentId?: string) {
    setEditingId(cat.id)
    setEditForm({
      name: cat.name,
      icon: cat.icon ?? "",
      color: cat.color ?? "#3b82f6",
      type: cat.type,
      parentId: parentId ?? ("parentId" in cat ? (cat.parentId ?? "") : ""),
    })
    setEditError("")
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault()
    if (!editingId) return
    setEditLoading(true)
    setEditError("")
    const res = await fetch("/api/categories", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: editingId,
        name: editForm.name,
        icon: editForm.icon || null,
        color: editForm.color || null,
        type: editForm.type,
        parentId: editForm.parentId || null,
      }),
    })
    setEditLoading(false)
    if (!res.ok) {
      const d = await res.json()
      setEditError(d.error)
    } else {
      setEditingId(null)
      load()
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Smazat kategorii? Transakce v této kategorii zůstanou bez kategorie.")) return
    const res = await fetch(`/api/categories?id=${id}`, { method: "DELETE" })
    if (!res.ok) {
      const d = await res.json()
      alert(d.error)
    } else {
      if (editingId === id) setEditingId(null)
      load()
    }
  }

  const topLevel = categories.filter((c) => !c.parentId)
  const defaultCats = topLevel.filter((c) => c.isDefault)
  const userCats = topLevel.filter((c) => !c.isDefault)
  const parentOptions = topLevel

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Kategorie</h1>
        <button
          onClick={() => {
            setShowForm(!showForm)
            setForm(emptyForm())
            setFormError("")
          }}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700"
        >
          + Přidat kategorii
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-medium mb-4">Nová kategorie</h2>
          <form onSubmit={handleCreate}>
            <CatFormFields form={form} parentOptions={parentOptions} onChange={setForm} />
            {formError && <p className="text-sm text-red-600 mt-3">{formError}</p>}
            <div className="flex gap-3 mt-4">
              <button
                type="submit"
                disabled={formLoading}
                className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                {formLoading ? "Ukládám..." : "Vytvořit"}
              </button>
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100"
              >
                Zrušit
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="space-y-8">
        {/* Custom categories */}
        {userCats.length > 0 && (
          <div>
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
              Vlastní kategorie
            </h2>
            <div className="space-y-2">
              {userCats.map((cat) => (
                <div key={cat.id}>
                  {editingId === cat.id ? (
                    <div className="bg-white border border-blue-200 rounded-xl p-4">
                      <form onSubmit={handleEdit}>
                        <CatFormFields
                          form={editForm}
                          parentOptions={parentOptions.filter((p) => p.id !== cat.id)}
                          onChange={setEditForm}
                        />
                        {editError && <p className="text-sm text-red-600 mt-3">{editError}</p>}
                        <div className="flex gap-2 mt-4">
                          <button
                            type="submit"
                            disabled={editLoading}
                            className="bg-blue-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-blue-700 disabled:opacity-50"
                          >
                            {editLoading ? "Ukládám..." : "Uložit"}
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditingId(null)}
                            className="px-3 py-1.5 rounded-lg text-xs font-medium text-gray-600 hover:bg-gray-100"
                          >
                            Zrušit
                          </button>
                        </div>
                      </form>
                    </div>
                  ) : (
                    <div className="bg-white border border-gray-200 rounded-xl p-4">
                      <div className="flex items-center gap-3">
                        {cat.color && (
                          <div
                            className="w-3 h-3 rounded-full shrink-0"
                            style={{ backgroundColor: cat.color }}
                          />
                        )}
                        <span className="text-lg">{cat.icon}</span>
                        <div className="flex-1 min-w-0">
                          <span className="font-medium text-sm text-gray-900">{cat.name}</span>
                          <span className="ml-2 text-xs text-gray-400">{TYPE_LABEL[cat.type]}</span>
                        </div>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => startEdit(cat)}
                            title="Upravit"
                            className="text-gray-300 hover:text-blue-500 p-1 rounded transition-colors"
                          >
                            <svg
                              xmlns="http://www.w3.org/2000/svg"
                              className="w-4 h-4"
                              viewBox="0 0 20 20"
                              fill="currentColor"
                            >
                              <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z" />
                            </svg>
                          </button>
                          <button
                            onClick={() => handleDelete(cat.id)}
                            title="Smazat"
                            className="text-gray-300 hover:text-red-500 p-1 rounded transition-colors text-xl leading-none"
                          >
                            ×
                          </button>
                        </div>
                      </div>
                      {/* Subcategories */}
                      {cat.children.length > 0 && (
                        <div className="mt-2 ml-6 space-y-1">
                          {cat.children.map((sub) => (
                            <div key={sub.id}>
                              {editingId === sub.id ? (
                                <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
                                  <form onSubmit={handleEdit}>
                                    <CatFormFields
                                      form={editForm}
                                      parentOptions={parentOptions}
                                      onChange={setEditForm}
                                    />
                                    {editError && (
                                      <p className="text-sm text-red-600 mt-2">{editError}</p>
                                    )}
                                    <div className="flex gap-2 mt-3">
                                      <button
                                        type="submit"
                                        disabled={editLoading}
                                        className="bg-blue-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-blue-700 disabled:opacity-50"
                                      >
                                        {editLoading ? "Ukládám..." : "Uložit"}
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => setEditingId(null)}
                                        className="px-3 py-1.5 rounded-lg text-xs font-medium text-gray-600 hover:bg-gray-100"
                                      >
                                        Zrušit
                                      </button>
                                    </div>
                                  </form>
                                </div>
                              ) : (
                                <div className="flex items-center gap-2 py-1">
                                  <span className="text-gray-300 text-xs">└</span>
                                  {sub.color && (
                                    <div
                                      className="w-2 h-2 rounded-full shrink-0"
                                      style={{ backgroundColor: sub.color }}
                                    />
                                  )}
                                  <span className="text-sm">{sub.icon}</span>
                                  <span className="text-sm text-gray-700">{sub.name}</span>
                                  <span className="text-xs text-gray-400">
                                    {TYPE_LABEL[sub.type]}
                                  </span>
                                  {!sub.isDefault && (
                                    <div className="flex items-center gap-1 ml-auto">
                                      <button
                                        onClick={() => startEdit(sub, cat.id)}
                                        title="Upravit"
                                        className="text-gray-300 hover:text-blue-500 p-1 rounded transition-colors"
                                      >
                                        <svg
                                          xmlns="http://www.w3.org/2000/svg"
                                          className="w-3 h-3"
                                          viewBox="0 0 20 20"
                                          fill="currentColor"
                                        >
                                          <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z" />
                                        </svg>
                                      </button>
                                      <button
                                        onClick={() => handleDelete(sub.id)}
                                        title="Smazat"
                                        className="text-gray-300 hover:text-red-500 p-1 rounded transition-colors text-lg leading-none"
                                      >
                                        ×
                                      </button>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {userCats.length === 0 && !showForm && (
          <div className="bg-white rounded-xl border border-dashed border-gray-300 p-8 text-center text-gray-400">
            Žádné vlastní kategorie. Přidej první pomocí tlačítka výše.
          </div>
        )}

        {/* Default categories */}
        <div>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Výchozí kategorie
          </h2>
          <div className="space-y-2">
            {defaultCats.map((cat) => (
              <div key={cat.id} className="bg-gray-50 rounded-xl p-4">
                <div className="flex items-center gap-3">
                  {cat.color && (
                    <div
                      className="w-3 h-3 rounded-full shrink-0"
                      style={{ backgroundColor: cat.color }}
                    />
                  )}
                  <span className="text-lg">{cat.icon}</span>
                  <div className="flex-1 min-w-0">
                    <span className="font-medium text-sm text-gray-700">{cat.name}</span>
                    <span className="ml-2 text-xs text-gray-400">{TYPE_LABEL[cat.type]}</span>
                  </div>
                  <span className="text-xs text-gray-400 bg-gray-200 px-2 py-0.5 rounded-full">
                    výchozí
                  </span>
                </div>
                {cat.children.length > 0 && (
                  <div className="mt-2 ml-6 space-y-1">
                    {cat.children.map((sub) => (
                      <div key={sub.id} className="flex items-center gap-2 py-0.5">
                        <span className="text-gray-300 text-xs">└</span>
                        <span className="text-sm">{sub.icon}</span>
                        <span className="text-sm text-gray-600">{sub.name}</span>
                        <span className="text-xs text-gray-400">{TYPE_LABEL[sub.type]}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
