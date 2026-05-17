export const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  bank: "Banka",
  broker: "Broker",
  exchange: "Exchange",
  cash: "Hotovost",
  crypto_wallet: "Crypto peněženka",
}

export const ACCOUNT_TYPES = [
  { value: "bank", label: "Banka (Raiffeisenbank...)" },
  { value: "broker", label: "Broker (T212, IBKR...)" },
  { value: "exchange", label: "Exchange (Anycoin, Binance...)" },
  { value: "cash", label: "Hotovost" },
  { value: "crypto_wallet", label: "Crypto peněženka" },
]
