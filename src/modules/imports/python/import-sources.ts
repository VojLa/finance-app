import type { PythonAccount } from "@/modules/accounts/account-contract"
import type { PythonImportSource } from "./import-contract"

export const IMPORT_SOURCE_OPTIONS = [
  {
    value: "raiffeisenbank",
    label: "Raiffeisenbank",
    accepts: ["bank"] as PythonAccount["type"][],
  },
  {
    value: "trading212",
    label: "Trading 212",
    accepts: ["broker"] as PythonAccount["type"][],
  },
  {
    value: "anycoin",
    label: "Anycoin",
    accepts: ["exchange"] as PythonAccount["type"][],
  },
] as const satisfies readonly {
  value: PythonImportSource
  label: string
  accepts: readonly PythonAccount["type"][]
}[]
