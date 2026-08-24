# Portfolio and dashboard read models

Type: domain
Status: current
Owns: authorized portfolio, dashboard and browser projection contracts
Code: `portfolio/`, `portfolio_snapshot/`, `dashboard_snapshot/`, browser modules
Update when: projection, presentation or read contract changes

Portfolio and financial dashboard are authorized projections over snapshot, current-value and net-worth evidence. Browser state preserves decimal strings and cannot calculate or recover finance from a legacy response.

Verification: [test matrix](testing.md).
