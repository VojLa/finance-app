## Account-currency presentation evidence

Type: historical
Status: historical
Owns: milestone evidence for account-currency presentation
Code: account, snapshot and read-model implementation at the recorded milestone
Update when: evidence is archived or replaced by a newer record

`Account.currency` is the intended denomination for primary account-level
presentation. It is distinct from `User.baseCurrency`, which owns the current
aggregate AccountSnapshot set, NetWorthSnapshot, portfolio aggregate,
dashboard global summary, and history.

The current physical AccountSnapshot contract does not store both
denominations. Its `currency` and scalar MONEY fields are the snapshot output
currency. Original/native components are preserved in selected
`*ByCurrency` JSONB fields, while `AccountSnapshotItem.value` and `costBasis`
are also output-currency values. Native item value and cost fields remain
component evidence rather than a complete account summary.

The calculation result includes `liabilities_value_by_currency` and verifies
it against the selected liability balance and direct output conversion.
Persistence uses that tuple for an audit, then omits it from
`ExpectedAccountSnapshotRow`; the physical AccountSnapshot table has no
`liabilitiesValueByCurrency` column. This makes an exact liability
account-currency read impossible from the persisted snapshot.

For mixed-native investment accounts, persisted snapshot rates contain only
the direct pairs consumed by the output-currency valuation. An EUR account
inside a CZK user snapshot can therefore contain `USD -> CZK` and
`EUR -> CZK`, but no `USD -> EUR`. Original-currency breakdowns cannot be
treated as account-currency totals, and the read layer must not infer an
inverse or cross rate.

R10-B's representability gate is consequently NOT READY. The planned R10-B1
remediation must establish complete write-time account-currency summary
evidence, persist liability-native evidence, and define an explicit supported
FX contract. Until then, account-level public scalar values remain accurately
identified as output-currency values rather than being relabeled.

## Account-currency companion snapshots

R10-B1 resolves the representability blocker through the existing
`AccountSnapshot(accountId, timestamp, currency, granularity)` identity. When
`Account.currency` differs from `User.baseCurrency`, the same refresh
atomically persists:

- a primary snapshot in `User.baseCurrency`; and
- an account-presentation companion in `Account.currency`.

The two rows have distinct deterministic IDs but identical account, timestamp,
granularity, source, calculation version, and selected canonical business
evidence. When the currencies match, the primary row serves both authorities
and no companion is created. Only primary IDs enter `NetWorthSnapshot`;
companions never increase its required account count.

Each companion owns all existing scalar MONEY fields and its own
`AccountSnapshotItem` rows in the account currency. Item native value,
native cost, and native currency fields remain unchanged source evidence. A
liability companion persists the exact native liability in
`liabilitiesValue`, so account-currency presentation no longer depends on a
missing `liabilitiesValueByCurrency` physical column.

The conversion contract consumes exactly one persisted direct observation at
snapshot write time. For foreign source A and target B, the expression is
`amount * rate(A -> B)`. Input evidence remains exact, while the derived
snapshot output rounds once with Decimal `ROUND_HALF_EVEN` at its explicit
final MONEY boundary. It does not invert, triangulate, or persist a synthetic
pair. A nonzero underflow, non-finite value, or destination overflow fails
closed. Native portfolio and total-net-worth `*ByCurrency` values retain their
QUANTITY precision and need not equal the rounded output-currency MONEY scalar.

Snapshot-time components use the direct pair as of the snapshot. Historical net
deposits, realized P/L, fees, and taxes select the direct pair as of each event.
Internal exchange-rate audit evidence records the exact persisted observation
ID. Missing, stale, future, wrong-direction, wrong-source, conflicting, or
non-representable evidence causes the complete write to fail closed. Version 2
pivot roles remain readable only for snapshots created before R11-J.

This remediation changes no public portfolio, dashboard, or history contract.
Those readers continue to consume the primary user-base snapshot until
R10-B2 performs the explicit account-currency presentation cutover.

## Account presentation and primary lineage

R10-B2 introduces no new financial persistence. It reads the R10-B1 pair as
two explicit authorities: the primary snapshot remains the account's
contribution to user-base aggregation, while the exact companion becomes the
account presentation. Both are selected at the same account, timestamp,
granularity, source, and calculation version in one repeatable-read
transaction.

For a public portfolio account, `snapshotId` identifies the snapshot that owns
the returned summary and positions, and `primarySnapshotId` identifies the
manifest-selected primary snapshot. Account-level `currency` is the persisted
`Account.currency`; every returned position value, cost basis, and unrealized
P/L uses that currency. Native fields and cash/deposit breakdowns retain their
original-currency evidence semantics.

Top-level portfolio summary and explicit aggregate positions remain in
`User.baseCurrency`. Dashboard global summary, allocation, and top positions
also remain primary-currency evidence, while dashboard account cards use the
companion. Missing or inconsistent companion evidence invalidates the exact
read; it is never synthesized from the primary row or reconstructed with FX.

## Dashboard net-deposit authority

R10-C makes the already persisted net-deposit scalar visible on both dashboard
levels. The global `netDepositsValue` remains part of the primary aggregate in
`User.baseCurrency`; it is not a sum of account-presentation values. Every
account card receives its own exact `netDepositsValue` from the R10-B2
presentation summary in `Account.currency`.

When account and user currencies match, `snapshotId == primarySnapshotId` is a
valid single physical authority. When they differ, `snapshotId` identifies the
companion that owns the account-currency value and `primarySnapshotId`
identifies the manifest-selected contribution to global finance. Deliberately
different primary and companion values therefore remain correct and cannot
cross into the other presentation boundary.

The value is signed MONEY evidence: negative net deposits and exact zero are
valid and visible. API serialization is a canonical six-decimal string, and
the browser rejects malformed successful responses rather than normalizing
them. R10-C does not reconstruct deposits from transactions, currency
breakdowns, history, holdings, or FX, and changes no snapshot calculation or
current-value semantics.
