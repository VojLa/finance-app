# Codex Rules For This Repo

This file is intended as persistent working memory for Codex.

Read this before substantial answers or edits.

## Product Direction

- Finance app with imports, investment ledger, holdings, portfolio snapshots, cash, and account views.
- Accounts have a main currency in `Account.currency`.
- Account-level portfolio/account pages should display primary values in the account's main currency.
- Currency breakdowns by individual currency should still be preserved and shown where useful.

## Snapshot And FX Rules

- Do not hard-code CZK for account snapshots.
- `AccountSnapshot.currency` should represent the account's main currency.
- `investmentValue`, `investmentCostBasis`, `netDepositsValue`, realized/unrealized P&L, fees, taxes, cash, and total value should be stored in the snapshot currency.
- Keep `*ByCurrency` JSON breakdowns for original/natural currencies.
- Invested/deposited values must use the FX rate from the event date, not today's FX rate.
- Current-day/live snapshot should start from the latest daily account snapshot and apply only events after that snapshot up to now.
- Avoid recomputing the whole history for today's live view when a previous snapshot exists.

## Import Rules

- Imports should be async where possible.
- Multi-file import should post-process holdings and snapshots once per source/account batch, not once per file.
- Unsupported rows should be shown as unread/parse issues, not as the full file preview table.

## Verification

- Prefer `npx.cmd tsc --noEmit`, `npm.cmd test`, and `npm.cmd run lint`.
- Avoid `npm run build` while the user is running `next dev`, because `.next` cache has repeatedly caused missing chunk/runtime errors.

## Local Dev Cache Note

If Next errors with missing chunk modules or `Cannot read properties of undefined (reading 'call')`, it is usually broken `.next` cache:

1. Stop dev server.
2. Delete `.next`.
3. Start `npm run dev -- -p 3010`.
