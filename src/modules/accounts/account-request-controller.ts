import type { PythonAccount } from "./account-contract"

type AccountListRequest = () => Promise<PythonAccount[]>

export function createAccountRequestController(request: AccountListRequest) {
  let initialRequestStarted = false

  return {
    initial(): Promise<PythonAccount[]> | null {
      if (initialRequestStarted) {
        return null
      }
      initialRequestStarted = true
      return request()
    },
    reload(): Promise<PythonAccount[]> {
      return request()
    },
  }
}
