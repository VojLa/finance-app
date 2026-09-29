## Account-currency presentation reads

Type: historical
Status: historical
Owns: milestone evidence for account-currency reads
Code: authorized snapshot/read-model implementation at the recorded milestone
Update when: evidence is archived or replaced by a newer record

R10-B2 keeps `build_multi_account_portfolio_view(primary_views)` unchanged as
the user-base aggregate authority. The authorized multi-account service reads
all primary manifest identities and all required account-currency companions
inside one `REPEATABLE READ` transaction. A same-currency account reuses its
primary row; a different-currency account requires one exact companion. There
is no latest, nearest, older, alternate-version, or read-time FX fallback.

The internal result separates `portfolio` from `account_presentations`.
Portfolio and dashboard global totals, allocations, top positions, NetWorth,
and history consume only the primary side. Portfolio account summaries and
positions, plus dashboard account cards, consume only the presentation side.
Public account lineage exposes the presentation `snapshotId` and manifest
`primarySnapshotId`; internal market and FX lineage remains private.

The Next workflow validates `primarySnapshotId` against the refresh manifest.
Portfolio account selection is local and uses the exact account-currency
summary and positions already returned by Python. Aggregate positions are an
explicit primary-currency collection, so mixed companion currencies never
enter the aggregate browser view. The read path is read-only and performs no
provider call, refresh, ledger replay, or financial arithmetic.
