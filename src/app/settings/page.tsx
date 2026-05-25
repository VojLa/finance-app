"use client"

import { useEffect, useState } from "react"
import { useSession, signOut } from "next-auth/react"

interface SharedAccount {
  id: string
  name: string
  type: string
  shareRole: string
  ownerEmail?: string
}

export default function SettingsPage() {
  const { data: session } = useSession()
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [pwSaving, setPwSaving] = useState(false)
  const [pwError, setPwError] = useState("")
  const [pwSuccess, setPwSuccess] = useState(false)

  const [sharedAccounts, setSharedAccounts] = useState<SharedAccount[]>([])

  useEffect(() => {
    fetch("/api/accounts")
      .then((r) => r.json())
      .then((data: (SharedAccount & { isShared?: boolean })[]) => {
        setSharedAccounts(data.filter((a) => a.isShared))
      })
  }, [])

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault()
    setPwError("")
    setPwSuccess(false)

    if (newPassword !== confirmPassword) {
      setPwError("Nová hesla se neshodují")
      return
    }

    setPwSaving(true)
    const res = await fetch("/api/auth/password", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ currentPassword, newPassword }),
    })
    setPwSaving(false)

    if (res.ok) {
      setPwSuccess(true)
      setCurrentPassword("")
      setNewPassword("")
      setConfirmPassword("")
    } else {
      const data = await res.json()
      setPwError(data.error ?? "Nepodařilo se změnit heslo")
    }
  }

  const INPUT_CLS =
    "w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold">Nastavení</h1>

      <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
        <h2 className="text-base font-medium text-gray-900">Profil</h2>
        <div>
          <p className="text-sm text-gray-500">E-mail</p>
          <p className="text-sm font-medium text-gray-900 mt-0.5">{session?.user?.email}</p>
        </div>
        {session?.user?.name && (
          <div>
            <p className="text-sm text-gray-500">Jméno</p>
            <p className="text-sm font-medium text-gray-900 mt-0.5">{session.user.name}</p>
          </div>
        )}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
        <h2 className="text-base font-medium text-gray-900">Změnit heslo</h2>
        <form onSubmit={handleChangePassword} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Současné heslo</label>
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              className={INPUT_CLS}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Nové heslo</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={8}
              className={INPUT_CLS}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Potvrdit nové heslo
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
              className={INPUT_CLS}
            />
          </div>
          {pwError && <p className="text-sm text-red-600">{pwError}</p>}
          {pwSuccess && <p className="text-sm text-green-600">Heslo bylo úspěšně změněno.</p>}
          <button
            type="submit"
            disabled={pwSaving}
            className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {pwSaving ? "Ukládám..." : "Změnit heslo"}
          </button>
        </form>
      </div>

      {sharedAccounts.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <h2 className="text-base font-medium text-gray-900">Sdílené přístupy</h2>
          <p className="text-sm text-gray-500">Tyto účty s tebou sdíleli jiní uživatelé.</p>
          <div className="divide-y divide-gray-100">
            {sharedAccounts.map((a) => (
              <div key={a.id} className="py-2.5 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-900">{a.name}</p>
                  <p className="text-xs text-gray-400">{a.type}</p>
                </div>
                <span
                  className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                    a.shareRole === "editor"
                      ? "bg-blue-50 text-blue-700"
                      : "bg-gray-100 text-gray-500"
                  }`}
                >
                  {a.shareRole === "editor" ? "Editor" : "Prohlížeč"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
        <h2 className="text-base font-medium text-gray-900">Účet</h2>
        <button
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="px-4 py-2 rounded-lg text-sm font-medium text-red-600 border border-red-200 hover:bg-red-50 transition-colors"
        >
          Odhlásit se
        </button>
      </div>
    </div>
  )
}
