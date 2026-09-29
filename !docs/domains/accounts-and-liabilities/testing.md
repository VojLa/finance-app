# Accounts and liabilities testing

Type: testing
Status: current
Owns: representative account isolation, lifecycle and liability verification
Code: account, membership, invitation and liability tests
Update when: domain risks or representative suites change

| Risk                               | Invariant       | Unit/contract evidence                                                       | Integration/recovery evidence                   |
| ---------------------------------- | --------------- | ---------------------------------------------------------------------------- | ----------------------------------------------- |
| Cross-account access               | `INV-AUTH-001`  | `test_account_access.py`, `test_account_membership_admin.py`                 | `test_account_membership_admin_integration.py`  |
| Invitation privilege escalation    | `INV-AUTH-001`  | `test_account_invitations.py`                                                | `test_account_invitations_integration.py`       |
| Archive deletes or exposes history | `INV-CANON-003` | `test_account_lifecycle.py`                                                  | `test_account_lifecycle_integration.py`         |
| Invalid liability evidence         | `INV-MONEY-001` | `test_liability_balance_evidence.py`, `test_manual_liability_balance_api.py` | liability evidence and writer integration tests |

Transport and UI contracts are covered by `src/modules/accounts/*.test.ts`.
