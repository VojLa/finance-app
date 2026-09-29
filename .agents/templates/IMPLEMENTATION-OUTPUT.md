# Implementation handoff

## Outcome

State the observable result in two to five sentences.

## Changed files

List each in-scope file once with its reason. Do not paraphrase the whole diff.

## Acceptance

| Criterion | Evidence | Result |
| --- | --- | --- |
| [original criterion] | [test/diff/reference] | PASS/FAIL/UNKNOWN |

## Verification

| Check | Command | Result |
| --- | --- | --- |
| Focused test | | PASS/FAIL/NOT RUN |
| Integration/contract | | PASS/FAIL/NOT APPLICABLE |
| Static/quality gate | | PASS/FAIL/NOT RUN |
| DB/API/generated check | | PASS/FAIL/NOT APPLICABLE |
| Documentation check | | PASS/FAIL/NOT APPLICABLE |

## Security, money, and data

Report actual evidence for authorization/account isolation, input validation,
sensitive logging, transaction/rollback, idempotency/concurrency, money/FX, and
schema ownership where relevant. Use `NOT APPLICABLE` rather than generic assurance.

## Deviations and residual risk

Disclose scope changes, unverified criteria, temporary paths, and follow-up work.
Write `None known` only when every original criterion has evidence.
