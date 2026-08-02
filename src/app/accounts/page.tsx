"use client"

import { useCallback, useEffect, useState } from "react"

import { ACCOUNT_TYPES, ACCOUNT_TYPE_LABELS } from "@/lib/constants"
import {
  AccountClientError,
  requestAccounts,
  requestArchiveAccount,
  requestCreateAccount,
  requestUpdateAccount,
} from "@/modules/accounts/account-client"
import type {
  AccountPageModel,
  CreateAccountRequest,
  UpdateAccountRequest,
} from "@/modules/accounts/account-contract"
import { toAccountPageModel } from "@/modules/accounts/account-contract"

type AccountsPageState =
  | { status: "loading" }
  | { status: "ready"; accounts: readonly AccountPageModel[] }
  | { status: "error"; code: string; message: string }

type AccountActionState =
  | { status: "idle" }
  | { status: "submitting"; action: "create" | "update" | "archive"; accountId?: string }
  | { status: "error"; action: "create" | "update" | "archive"; message: string }

type EditForm = {
  name: string
  currency: string
}

function safeActionMessage(error: unknown): string {
  return error instanceof AccountClientError ? error.message : "Operaci se nepodařilo dokončit."
}

export default function AccountsPage() {
  const [pageState, setPageState] = useState<AccountsPageState>({ status: "loading" })
  const [actionState, setActionState] = useState<AccountActionState>({ status: "idle" })
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [name, setName] = useState("")
  const [type, setType] = useState<CreateAccountRequest["type"]>("broker")
  const [currency, setCurrency] = useState("EUR")
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<EditForm>({ name: "", currency: "" })

  const loadAccounts = useCallback(async () => {
    setPageState({ status: "loading" })
    try {
      const accounts = await requestAccounts()
      setPageState({
        status: "ready",
        accounts: accounts.map(toAccountPageModel),
      })
    } catch (error) {
      if (error instanceof AccountClientError) {
        setPageState({ status: "error", code: error.code, message: error.message })
      } else {
        setPageState({
          status: "error",
          code: "python_api_unavailable",
          message: "Účty se nepodařilo načíst.",
        })
      }
    }
  }, [])

  useEffect(() => {
    void loadAccounts()
  }, [loadAccounts])

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault()
    setActionState({ status: "submitting", action: "create" })
    const payload: CreateAccountRequest = {
      name,
      type,
      currency,
    }
    try {
      await requestCreateAccount(payload)
      setName("")
      setType("broker")
      setCurrency("EUR")
      setShowCreateForm(false)
      setActionState({ status: "idle" })
      await loadAccounts()
    } catch (error) {
      setActionState({
        status: "error",
        action: "create",
        message: safeActionMessage(error),
      })
    }
  }

  function startEditing(account: AccountPageModel) {
    setEditingId(account.id)
    setEditForm({ name: account.name, currency: account.currency })
    setActionState({ status: "idle" })
  }

  async function handleUpdate(accountId: string) {
    setActionState({ status: "submitting", action: "update", accountId })
    const payload: UpdateAccountRequest = {
      name: editForm.name,
      currency: editForm.currency,
    }
    try {
      await requestUpdateAccount(accountId, payload)
      setEditingId(null)
      setActionState({ status: "idle" })
      await loadAccounts()
    } catch (error) {
      setActionState({
        status: "error",
        action: "update",
        message: safeActionMessage(error),
      })
    }
  }

  async function handleArchive(account: AccountPageModel) {
    const confirmed = window.confirm(
      `Archivovat účet „${account.name}“?\n\nÚčet bude archivován. Jeho finanční data nebudou smazána.`
    )
    if (!confirmed) {
      return
    }
    setActionState({ status: "submitting", action: "archive", accountId: account.id })
    try {
      await requestArchiveAccount(account.id)
      setActionState({ status: "idle" })
      await loadAccounts()
    } catch (error) {
      setActionState({
        status: "error",
        action: "archive",
        message: safeActionMessage(error),
      })
    }
  }

  const accounts = pageState.status === "ready" ? pageState.accounts : []
  const createPending = actionState.status === "submitting" && actionState.action === "create"

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Účty</h1>
          <p className="text-sm text-gray-500 mt-1">
            Správa metadat účtů. Finanční hodnoty najdete v portfoliu a dashboardu.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setShowCreateForm((visible) => !visible)
            setActionState({ status: "idle" })
          }}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700"
        >
          {showCreateForm ? "Zrušit" : "Přidat účet"}
        </button>
      </div>

      {showCreateForm && (
        <form
          onSubmit={handleCreate}
          className="bg-white border border-gray-200 rounded-xl p-5 mb-6 space-y-4"
        >
          <h2 className="font-semibold text-gray-900">Nový účet</h2>
          <div className="grid gap-4 sm:grid-cols-3">
            <label className="text-sm text-gray-700">
              Název
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </label>
            <label className="text-sm text-gray-700">
              Typ
              <select
                value={type}
                onChange={(event) => setType(event.target.value as CreateAccountRequest["type"])}
                className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
              >
                {ACCOUNT_TYPES.map((accountType) => (
                  <option key={accountType.value} value={accountType.value}>
                    {accountType.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm text-gray-700">
              Měna
              <input
                value={currency}
                onChange={(event) => setCurrency(event.target.value)}
                required
                maxLength={3}
                className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2 uppercase"
              />
            </label>
          </div>
          {actionState.status === "error" && actionState.action === "create" && (
            <p className="text-sm text-red-600">{actionState.message}</p>
          )}
          <button
            type="submit"
            disabled={createPending}
            className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
          >
            {createPending ? "Vytvářím…" : "Vytvořit účet"}
          </button>
        </form>
      )}

      {pageState.status === "loading" && (
        <div className="bg-white border border-gray-200 rounded-xl p-8 text-center text-gray-500">
          Načítám účty…
        </div>
      )}

      {pageState.status === "error" && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-5">
          <p className="font-medium text-red-800">Účty se nepodařilo načíst</p>
          <p className="text-sm text-red-700 mt-1">{pageState.message}</p>
        </div>
      )}

      {pageState.status === "ready" && accounts.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-8 text-center">
          <p className="font-medium text-gray-900">Zatím nemáte žádný aktivní účet</p>
          <p className="text-sm text-gray-500 mt-1">Vytvořte první účet pomocí tlačítka výše.</p>
        </div>
      )}

      {pageState.status === "ready" && accounts.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {accounts.map((account) => {
            const updatePending =
              actionState.status === "submitting" &&
              actionState.action === "update" &&
              actionState.accountId === account.id
            const archivePending =
              actionState.status === "submitting" &&
              actionState.action === "archive" &&
              actionState.accountId === account.id

            return (
              <article key={account.id} className="bg-white border border-gray-200 rounded-xl p-5">
                {editingId === account.id ? (
                  <div className="space-y-3">
                    <label className="block text-sm text-gray-700">
                      Název
                      <input
                        value={editForm.name}
                        onChange={(event) =>
                          setEditForm((current) => ({ ...current, name: event.target.value }))
                        }
                        className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
                      />
                    </label>
                    <div className="text-sm text-gray-700">
                      Typ
                      <p className="mt-1 px-3 py-2 rounded-lg bg-gray-50 text-gray-600">
                        {ACCOUNT_TYPE_LABELS[account.type] ?? account.type}
                      </p>
                    </div>
                    <label className="block text-sm text-gray-700">
                      Měna
                      <input
                        value={editForm.currency}
                        onChange={(event) =>
                          setEditForm((current) => ({
                            ...current,
                            currency: event.target.value,
                          }))
                        }
                        maxLength={3}
                        className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2 uppercase"
                      />
                    </label>
                    {actionState.status === "error" && actionState.action === "update" && (
                      <p className="text-sm text-red-600">{actionState.message}</p>
                    )}
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => void handleUpdate(account.id)}
                        disabled={updatePending}
                        className="bg-blue-600 text-white px-3 py-2 rounded-lg text-sm disabled:opacity-50"
                      >
                        {updatePending ? "Ukládám…" : "Uložit"}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setEditingId(null)
                          setActionState({ status: "idle" })
                        }}
                        className="px-3 py-2 rounded-lg text-sm text-gray-600"
                      >
                        Zrušit
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex items-start gap-3">
                      <span
                        className="w-3 h-3 rounded-full mt-1.5"
                        style={{ backgroundColor: account.color ?? "#6b7280" }}
                      />
                      <div>
                        <h2 className="font-semibold text-gray-900">{account.name}</h2>
                        <p className="text-sm text-gray-500">
                          {ACCOUNT_TYPE_LABELS[account.type] ?? account.type} · {account.currency}
                        </p>
                      </div>
                    </div>
                    {actionState.status === "error" && actionState.action === "archive" && (
                      <p className="text-sm text-red-600 mt-3">{actionState.message}</p>
                    )}
                    <div className="flex gap-3 mt-5 pt-4 border-t border-gray-100">
                      <button
                        type="button"
                        onClick={() => startEditing(account)}
                        className="text-sm text-blue-600 hover:text-blue-800"
                      >
                        Upravit
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleArchive(account)}
                        disabled={archivePending}
                        className="text-sm text-amber-700 hover:text-amber-900 disabled:opacity-50"
                      >
                        {archivePending ? "Archivuji…" : "Archivovat účet"}
                      </button>
                    </div>
                  </>
                )}
              </article>
            )
          })}
        </div>
      )}
    </div>
  )
}
