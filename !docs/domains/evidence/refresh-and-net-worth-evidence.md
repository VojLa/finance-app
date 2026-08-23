## Coordinated snapshot-refresh plan

The pure 5K-A contract describes a complete coordinated refresh without
executing it. Current active broker, exchange, crypto-wallet, credit-card, loan,
and mortgage accounts each produce one immutable target. An active bank, cash,
or savings account invalidates the complete plan. A consistently archived
account is excluded from current-state coverage; contradictory archive fields
fail closed. An empty active set is valid and still yields a final net-worth
target.

Membership capability remains explicit: owner, admin, and editor may refresh an
account snapshot; viewer may only reuse an exact existing snapshot. The latter
is not a write grant. Every target uses the User base currency as its required
output currency while retaining the Account currency. Different currencies
mean exact FX evidence will be required later, but 5K-A neither selects nor
applies FX.

The final net-worth target contains every active account identity in
deterministic order and depends on exact AccountSnapshots sharing its timestamp,
granularity, output currency, and calculation version. It cannot run until all
write-capable and reuse-only targets are satisfied. This is only a declarative
dependency: 5K-A reads no database state, invokes no writer, and performs no
financial calculation. 5K-C1 establishes pure calculation, 5K-C2 read-only
persisted evidence selection, 5K-C3 pure physical projection, and 5K-C4
output-currency writer identity, locking, and replay. 5K-C5 exposes optional
manual output currency. Mixed-currency coordinated execution remains 5K-D.

The read-only 5K-B boundary turns persisted current state into immutable
coverage evidence. The persisted User exclusively supplies the output/base
currency, while each persisted AccountMember supplies role, relation, and
acceptance. Every joined row is retained for 5K-A validation; SQL does not
filter archived, unsupported, or incomplete evidence.

After one pure 5K-A call, owner/admin/editor targets remain future writer
targets regardless of existing rows. Viewer targets require exactly one
AccountSnapshot matching account, timestamp, granularity, User base currency,
and calculation version. Existing source and persistence timestamps are
structurally validated but source equality with the orchestration is not
required. The selected output contains only immutable account/snapshot
identities, never ORM or financial values.

This coverage proof is intentionally not financial validation. A structurally
eligible reused AccountSnapshot may still be financially corrupt, which must
fail later in the complete 5J-B validation. 5K-B requires coherent
`REPEATABLE READ` or `SERIALIZABLE`, owns no transaction or lock, disables
autoflush, and performs no write.

## Exact coordinated net-worth dependencies

5K-D is split into an exact dependency guard (5K-D1) and the later coordinated
executor (5K-D2). A guarded internal NetWorth write may declare one immutable,
unique, already sorted tuple of `(account_id, AccountSnapshot.id)` identities.
`None` means the existing manual selection of every current active supported
account; `()` means the exact current account set must be empty.

The guard is not a caller-selected account filter. Net-worth evidence still
loads the persisted User and complete current Account/AccountMember access set,
derives active supported accounts, and requires exact ordered account-ID
equality. It then selects the same-bucket, same-granularity, same-output-
currency, same-version AccountSnapshots and requires exact ordered pair
equality. Added, removed, archived, or same-count-substituted accounts and
replaced snapshot identities all fail closed.

The same tuple is checked in every SERIALIZABLE writer attempt and again
against the physical projection audit before replay or creation. It is returned
only in the internal writer result so 5K-D2 can compare completed refresh
outputs with final net-worth dependencies. It is not persisted in
NetWorthSnapshot, does not change physical identity, and is absent from the
manual HTTP request and response.

5K-D2 turns one exact 5K-B coverage result into a coordinated execution without
moving any financial rule into orchestration. Its initial caller-owned
`REPEATABLE READ` transaction establishes the complete current User, account,
membership, role, output-currency, and viewer-reuse set. The transaction closes
before any write. Every owner/admin/editor target then receives one independent
AccountSnapshot writer call; every viewer target contributes its already
persisted snapshot identity and never invokes that writer.

The combined immutable lineage is ordered by the plan's complete account set
and guarded by 5K-D1 during the final NetWorth write. Added, removed, archived,
or same-count-substituted access after coverage cannot produce a stale
NetWorthSnapshot. Each domain writer owns and commits its own transaction, so
successful account snapshots survive a later failure. Re-execution invokes all
refresh targets again and uses exact physical replay—not in-memory state—as the
only resume mechanism. No compensation, overwrite, repair, cross-stage outer
transaction, job-state model, or new persisted lineage is introduced. 5K-E1
and 5K-E2 are the implemented endpoint, authorization, and post-import
integration boundary.

## Authorized coordinated manual refresh

5K-E is decomposed into the 5K-E1 manual endpoint and 5K-E2
import/post-processing integration. E1 targets exactly the authenticated
principal's user and accepts no body, user/account IDs, currency, timestamp,
granularity, or lineage. One server clock value becomes a naive UTC minute
bucket used for all refresh timestamps after the authentication read
transaction has been committed and the shared session is idle.

R5-B3B projects that bucket and principal into one exact R5-B3A command. The
production market stage runs first; only its successful validated result may
start the coordinated executor. That nested executor remains the source of
persisted User base currency, complete account coverage, refresh versus viewer
reuse-only classification, source AccountSnapshot lineage, and final guarded
NetWorth creation. Since 5M-A, the public result also exposes the exact read
manifest consisting of the executor timestamp, granularity, output currency,
calculation version, and every validated `(account_id, snapshot_id)` identity
in deterministic executor order. This is the only public account/source
lineage: when non-empty, it calls the existing exact 5L portfolio and dashboard
reads without another database query, account discovery, latest selection,
sort, or fallback.

Market and snapshot persistence are separate committed phases. Market failure
prevents every snapshot writer. A later snapshot failure preserves committed
market evidence, and a zero-requirement market plan proceeds normally.
Production cross-currency endpoint refresh supports foreign-to-CZK evidence
through ČNB. Unsupported direct non-CZK pairs fail generically before snapshot
execution and never fall back to ECB, inverse, cross-rate, or manual evidence.
No market ID, provider identity, or market count enters the public result.

Every successful non-empty manifest is directly compatible with both 5L
request contracts and is transported unchanged. A successful empty manifest
has exactly `accounts == []`, zero selected and account-snapshot counts, and
represents the explicit state that the user has no snapshot-capable account.
It is complete rather than partial and does not arise from an error, fallback,
or latest-snapshot lookup. The 5L endpoints continue to require a non-empty
account set, so 5M-B must return an explicit empty workflow state before either
5L call and must not discover accounts or manufacture a synthetic selector.

The result otherwise exposes only the NetWorth snapshot identity and
disposition plus aggregate execution counts. It never exposes user identity,
memberships, roles, refresh modes, writer dispositions, FX evidence,
projections, selected item identities, or audits. A partial or inconsistent
manifest and other missing/incomplete evidence use the generic unavailable
HTTP 409 contract; immutable conflict retains its distinct generic HTTP 409
contract, neither identifying the failing account.

After a successful market stage, each AccountSnapshot writer commits
independently, so an unavailable response can coexist with valid completed
account rows and valid market evidence. The next identical request resumes
through exact replay and creates NetWorth only after all required identities
are complete. E1 introduces no compensation, persisted execution state,
migration, automatic retry, scheduler, worker, background job, or background
execution.
