# Identity and access testing

| Risk | Invariant | Evidence |
| --- | --- | --- |
| Principal spoofing | `INV-AUTH-001` | `test_auth_*`, `test_account_access.py` |
| Token leakage | `INV-AUTH-003` | internal-token and adapter tests |
| Unsafe errors | `INV-INPUT-002` | error and request-context tests |
