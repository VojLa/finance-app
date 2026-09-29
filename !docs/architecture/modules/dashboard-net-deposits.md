## Dashboard deposited presentation

Type: historical
Status: historical
Owns: milestone evidence for dashboard deposited presentation
Code: dashboard projection at the recorded milestone
Update when: evidence is archived or replaced by a newer record

R10-C completes the existing dashboard net-deposit presentation without
introducing a financial calculation. `DashboardSnapshotSummary` and the global
response continue copying `netDepositsValue` from the primary portfolio
aggregate in `User.baseCurrency`. `DashboardAccountCard` now also retains the
exact `net_deposits_value` from its R10-B2 account presentation summary and
serializes it as the required canonical MONEY string.

For a same-currency account, the primary identity owns both global contribution
and account presentation. For a mixed-currency account, the global amount is
owned by the manifest-selected primary snapshot while the account-card amount
is owned by the exact companion snapshot in `Account.currency`. The dashboard
reader never sums companion values into the aggregate and never relabels a
primary value as an account-currency value.

The browser contract requires `netDepositsValue` on every account card. Summary
and account components only format the server-provided exact string, preserving
negative and zero values. They perform no FX, arithmetic, finance lookup,
additional request, or legacy fallback. Missing or corrupt companion evidence
continues to fail closed before presentation.
