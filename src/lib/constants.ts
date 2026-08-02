import type { PythonAccount } from "@/modules/accounts/account-contract"

export const ACCOUNT_TYPE_LABELS: Record<PythonAccount["type"], string> = {
  bank: "Bankovní účet",
  cash: "Hotovost",
  savings: "Spořicí účet",
  broker: "Broker",
  exchange: "Kryptoměnová burza",
  crypto_wallet: "Kryptoměnová peněženka",
  credit_card: "Kreditní karta",
  loan: "Úvěr",
  mortgage: "Hypotéka",
}

export const ACCOUNT_TYPES = [
  { value: "bank", label: ACCOUNT_TYPE_LABELS.bank },
  { value: "cash", label: ACCOUNT_TYPE_LABELS.cash },
  { value: "savings", label: ACCOUNT_TYPE_LABELS.savings },
  { value: "broker", label: ACCOUNT_TYPE_LABELS.broker },
  { value: "exchange", label: ACCOUNT_TYPE_LABELS.exchange },
  { value: "crypto_wallet", label: ACCOUNT_TYPE_LABELS.crypto_wallet },
  { value: "credit_card", label: ACCOUNT_TYPE_LABELS.credit_card },
  { value: "loan", label: ACCOUNT_TYPE_LABELS.loan },
  { value: "mortgage", label: ACCOUNT_TYPE_LABELS.mortgage },
] as const satisfies readonly { value: PythonAccount["type"]; label: string }[]
