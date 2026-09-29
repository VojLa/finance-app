# Read-model testing

Type: testing
Status: current
Owns: representative authorization, projection and browser-boundary verification
Code: portfolio, snapshot, dashboard and frontend read-model tests
Update when: read-model risks or representative suites change

| Risk                                    | Invariant          | Unit/contract evidence                        | Integration/frontend evidence                      |
| --------------------------------------- | ------------------ | --------------------------------------------- | -------------------------------------------------- |
| Unauthorized read                       | `INV-AUTH-001`     | authorized reader/service tests               | portfolio auth/API integration tests               |
| Mixed account or snapshot identity      | `INV-PUBLISH-002`  | snapshot aggregation/projection tests         | portfolio/dashboard snapshot API integration tests |
| Currency breakdown used as total        | `INV-CURRENCY-002` | currency breakdown and account-currency tests | snapshot page-model/component tests                |
| Browser calculation fallback            | `INV-AUTH-002`     | portfolio/dashboard cutover tests             | clean-main/final-audit frontend tests              |
| Unknown cost basis replaced by estimate | `INV-VALUE-002`    | unknown-basis public tests                    | `unknown-cost-basis-ui.test.ts`                    |
