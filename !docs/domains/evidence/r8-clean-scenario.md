## R8 clean production scenario

R8 proves the current model from clean persisted state without introducing a
new financial source. One CZK user owns three API-created accounts: a CZK bank
account and EUR broker/exchange accounts. Source-format Raiffeisenbank,
Trading212, and Anycoin files create canonical Transactions,
InvestmentEvents, InvestmentMovements, Holdings, exact provider aliases,
market evidence, AccountSnapshots, and NetWorthSnapshots through their
production application boundaries.

The user base currency owns every scalar snapshot, portfolio, dashboard, and
history value. `cashValueByCurrency` and `netDepositsByCurrency` continue to
preserve original currencies. Production ČNB evidence remains direct
foreign-currency-to-CZK only; the architecture does not infer inverse or cross
rates. CoinGecko and Twelve Data identities remain explicit immutable aliases
created through the server-operator CLI.

Replay is defined by stable canonical financial tuples and deterministic
market/snapshot identities, not by creating duplicate finance rows. Equivalent
re-import rows become duplicate/skipped evidence, and current public
portfolio, dashboard, and history values do not drift.

Dashboard allocation percentages are presentation evidence derived from exact
position values. R8 permits deterministic four-decimal largest-remainder
projection so repeating ratios are representable while every non-empty
allocation set totals exactly `100.0000`. This does not alter value, cost,
cash, liability, profit/loss, or FX meaning.
