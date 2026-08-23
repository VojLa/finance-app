## Account-currency presentation representability

The R10-B evidence gate found that the current snapshot read model cannot
truthfully expose a complete account-currency presentation summary. The
snapshot projection validates both `Account.currency` and the caller's output
currency, but physically persists all scalar AccountSnapshot values in the
output currency. Portfolio account summaries and dashboard account cards copy
those scalars and explicitly format them with that output currency.

Native `cashValueByCurrency`, `investmentValueByCurrency`,
`investmentCostBasisByCurrency`, `netDepositsByCurrency`,
`realizedPnlByCurrency`, nullable `unrealizedPnlByCurrency`,
`feesByCurrency`, and `taxesByCurrency` preserve original currency evidence.
They are not account-currency totals. The calculation layer also validates
`liabilities_value_by_currency`, but the persistence row, SQLAlchemy model,
and physical AccountSnapshot table do not store that field.

For a CZK-output user with an EUR account and USD position, production snapshot
evidence contains direct `USD -> CZK` and, when required, `EUR -> CZK`
observations. It does not contain direct `USD -> EUR`; ČNB production
composition supports only foreign-currency-to-CZK evidence. The portfolio
reader cannot create an EUR total without a new provider capability or an
explicitly approved server-side cross-rate contract.

R10-B therefore changes no production module or public contract and is
completed with verdict NOT READY. The planned R10-B1 remediation must define
and persist a complete immutable account-currency valuation summary, including
liability evidence, and decide the exact direct-versus-derived FX contract
before portfolio/dashboard presentation changes.
