# Identity and access testing

Type: testing
Status: current
Owns: representative identity, token and safe-error verification
Code: `backend/python/tests/test_auth_*`, identity adapter tests and account-access tests
Update when: identity risks, contracts or representative suites change

| Risk                                          | Invariant                             | Unit/contract evidence                                 | Integration/boundary evidence                              |
| --------------------------------------------- | ------------------------------------- | ------------------------------------------------------ | ---------------------------------------------------------- |
| Invalid credentials or token                  | `INV-AUTH-001`                        | `test_auth_credentials.py`, `test_auth_token.py`       | `test_auth_credentials_integration.py`, `test_auth_api.py` |
| Principal spoofing                            | `INV-AUTH-001`                        | `test_account_access.py`                               | `test_portfolio_auth_api.py`                               |
| Token exposed to browser                      | `INV-AUTH-003`                        | `src/modules/python-api/server/internal-token.test.ts` | `src/modules/auth/r11-auth-boundary.test.ts`               |
| Base-currency mutation races or stale history | `INV-CURRENCY-001`, `INV-HISTORY-002` | `test_auth_base_currency.py`                           | disposable PostgreSQL history-invalidation acceptance      |
| Unsafe error or log                           | `INV-INPUT-002`                       | `test_errors.py`, `test_request_context.py`            | auth route and adapter tests                               |

Health behavior is covered by `test_health.py`; the exhaustive list remains in the
[test inventory](../../map/generated/TEST-INVENTORY.md).
