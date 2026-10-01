# Persistence model ownership

Type: reference
Status: current
Owns: semantic ownership of SQLAlchemy model groups
Code: `backend/python/app/db/models/`
Update when: a model group changes domain owner or persistence meaning

| Model group                                       | Semantic owner           | Main evidence                                                  |
| ------------------------------------------------- | ------------------------ | -------------------------------------------------------------- |
| common and enums                                  | persistence platform     | shared SQLAlchemy base types and persisted enum identities     |
| users                                             | identity and access      | credential/principal records                                   |
| accounts                                          | accounts and liabilities | account, membership, invitation and lifecycle                  |
| liabilities                                       | accounts and liabilities | dated liability balances                                       |
| transactions, categories, budgets, counterparties | cash flow                | canonical cash and operational classification/plans            |
| assets, holdings, ledger, canonical lineage       | investments and holdings | investment identity/history and derived Holdings               |
| imports, background jobs, publication targets     | imports and jobs         | durable input, lifecycle and publication coordination          |
| prices, market health, alias audit                | market data and FX       | immutable observations, runtime health and operator decisions  |
| snapshots                                         | valuation                | account and net-worth snapshot evidence                        |
| portfolio history                                 | portfolio history        | invalidation, jobs, generations, points and replay checkpoints |

SQLAlchemy model classes map the complete runtime schema but do not own migration
history. Alembic revisions and checked schema artifacts remain executable authority.
Exact class and revision facts are in the [DB inventory](../map/generated/DB-INVENTORY.md).

Within the investment model, `Asset` owns economic identity, `AssetListing` owns a
venue/currency listing, and `AssetAlias` may bind an external provider identity to
that listing. `PriceSnapshot` owns immutable native-price evidence and its exact
provider-symbol lineage. `Holding` remains a derived current projection and does not
become investment history or provider identity.

`MarketDataListingHealth` is mutable operational coordination for one exact
listing/provider pair; it is not financial evidence. `AssetAliasAudit` is an
append-only record of explicit global identity decisions and cannot be updated or
deleted through the database.
