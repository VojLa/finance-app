"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"

const INVESTMENT_ACCOUNT_TYPES = ["broker", "exchange", "crypto_wallet"]

const TX_TYPES = [
  { value: "buy", label: "Nákup" },
  { value: "sell", label: "Prodej" },
  { value: "dividend", label: "Dividenda" },
  { value: "interest", label: "Úrok" },
  { value: "staking_reward", label: "Staking odměna" },
  { value: "deposit", label: "Vklad" },
  { value: "withdrawal", label: "Výběr" },
  { value: "fee", label: "Poplatek" },
  { value: "currency_conversion", label: "Konverze měny" },
  { value: "airdrop", label: "Airdrop" },
]

const ASSET_TYPES = [
  { value: "stock", label: "Akcie" },
  { value: "etf", label: "ETF" },
  { value: "crypto", label: "Krypto" },
  { value: "commodity", label: "Komodita" },
  { value: "bond", label: "Dluhopis" },
  { value: "cash", label: "Hotovost" },
  { value: "other", label: "Jiné" },
]

const CURRENCIES = ["EUR", "USD", "CZK", "GBP", "BTC", "ETH", "USDT"]

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {children}
    </div>
  )
}

const INPUT_CLS =
  "w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"

export default function AddTransactionPage() {
  const router = useRouter()
  const [accounts, setAccounts] = useState<{ id: string; name: string; type: string }[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  const [accountId, setAccountId] = useState("")
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [type, setType] = useState("buy")
  const [symbol, setSymbol] = useState("")
  const [name, setName] = useState("")
  const [assetType, setAssetType] = useState("stock")
  const [quantity, setQuantity] = useState("")
  const [pricePerUnit, setPricePerUnit] = useState("")
  const [priceCurrency, setPriceCurrency] = useState("EUR")
  const [totalAmount, setTotalAmount] = useState("")
  const [totalCurrency, setTotalCurrency] = useState("EUR")
  const [fee, setFee] = useState("")
  const [feeCurrency, setFeeCurrency] = useState("EUR")

  useEffect(() => {
    fetch("/api/accounts")
      .then((r) => r.json())
      .then((data: { id: string; name: string; type: string }[]) => {
        const inv = data.filter((a) => INVESTMENT_ACCOUNT_TYPES.includes(a.type))
        setAccounts(inv)
        if (inv.length > 0) setAccountId(inv[0].id)
      })
  }, [])

  const needsAsset = ["buy", "sell", "dividend", "interest", "staking_reward", "airdrop"].includes(
    type
  )

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError("")

    const res = await fetch("/api/portfolio/transactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        accountId,
        date,
        type,
        symbol: needsAsset && symbol ? symbol : null,
        name: needsAsset && name ? name : null,
        assetType: needsAsset ? assetType : null,
        quantity: needsAsset && quantity ? parseFloat(quantity) : null,
        pricePerUnit: needsAsset && pricePerUnit ? parseFloat(pricePerUnit) : null,
        priceCurrency: needsAsset ? priceCurrency : null,
        totalAmount: totalAmount ? parseFloat(totalAmount) : null,
        totalCurrency,
        fee: fee ? parseFloat(fee) : null,
        feeCurrency: fee ? feeCurrency : null,
      }),
    })

    if (res.ok) {
      router.push("/portfolio")
    } else {
      const data = await res.json()
      setError(data.error ?? "Nepodařilo se uložit transakci.")
      setSaving(false)
    }
  }

  if (accounts.length === 0 && accountId === "") {
    return (
      <div className="max-w-xl space-y-6">
        <div className="flex items-center gap-3">
          <Link href="/portfolio" className="text-gray-400 hover:text-gray-600 text-sm">
            ← Portfolio
          </Link>
          <h1 className="text-2xl font-semibold">Přidat transakci</h1>
        </div>
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-sm text-amber-800">
          Nejprve vytvoř investiční účet (broker, exchange nebo crypto peněženku) v sekci Účty.
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-xl space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/portfolio" className="text-gray-400 hover:text-gray-600 text-sm">
          ← Portfolio
        </Link>
        <h1 className="text-2xl font-semibold">Přidat transakci</h1>
      </div>

      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-xl border border-gray-200 p-6 space-y-4"
      >
        {error && <div className="text-red-600 text-sm bg-red-50 rounded-lg p-3">{error}</div>}

        <Field label="Účet">
          <select
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            required
            className={INPUT_CLS}
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Datum">
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              required
              className={INPUT_CLS}
            />
          </Field>

          <Field label="Typ">
            <select value={type} onChange={(e) => setType(e.target.value)} className={INPUT_CLS}>
              {TX_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
        </div>

        {needsAsset && (
          <>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Symbol">
                <input
                  type="text"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  placeholder="AAPL, BTC..."
                  className={INPUT_CLS + " font-mono"}
                />
              </Field>

              <Field label="Typ aktiva">
                <select
                  value={assetType}
                  onChange={(e) => setAssetType(e.target.value)}
                  className={INPUT_CLS}
                >
                  {ASSET_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <Field label="Název (volitelné)">
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Apple Inc."
                className={INPUT_CLS}
              />
            </Field>

            <div className="grid grid-cols-2 gap-4">
              <Field label="Množství">
                <input
                  type="number"
                  step="any"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  placeholder="0"
                  className={INPUT_CLS + " font-mono"}
                />
              </Field>

              <Field label="Cena / ks">
                <div className="flex gap-2">
                  <input
                    type="number"
                    step="any"
                    value={pricePerUnit}
                    onChange={(e) => setPricePerUnit(e.target.value)}
                    placeholder="0"
                    className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <select
                    value={priceCurrency}
                    onChange={(e) => setPriceCurrency(e.target.value)}
                    className="w-20 border border-gray-300 rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {CURRENCIES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
              </Field>
            </div>
          </>
        )}

        <div className="grid grid-cols-2 gap-4">
          <Field label="Celková částka">
            <div className="flex gap-2">
              <input
                type="number"
                step="any"
                value={totalAmount}
                onChange={(e) => setTotalAmount(e.target.value)}
                placeholder="0"
                className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <select
                value={totalCurrency}
                onChange={(e) => setTotalCurrency(e.target.value)}
                className="w-20 border border-gray-300 rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {CURRENCIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
          </Field>

          <Field label="Poplatek (volitelné)">
            <div className="flex gap-2">
              <input
                type="number"
                step="any"
                value={fee}
                onChange={(e) => setFee(e.target.value)}
                placeholder="0"
                className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <select
                value={feeCurrency}
                onChange={(e) => setFeeCurrency(e.target.value)}
                className="w-20 border border-gray-300 rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {CURRENCIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
          </Field>
        </div>

        <div className="flex gap-3 pt-2">
          <button
            type="submit"
            disabled={saving || !accountId}
            className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Ukládám..." : "Přidat transakci"}
          </button>
          <Link
            href="/portfolio"
            className="px-5 py-2 text-sm text-gray-500 hover:bg-gray-100 rounded-lg"
          >
            Zrušit
          </Link>
        </div>
      </form>
    </div>
  )
}
