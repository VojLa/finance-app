# Decisions

Tato slozka drzi architektonicka a systemova rozhodnuti ve stylu ADR.

## Jak ADR pouzivat

- kazde rozhodnuti ma kratky a stabilni nazev
- nove ADR se pridava s dalsim cislem
- prijate ADR se zpetne neprepisuje tak, aby zmizel puvodni kontext
- pokud se rozhodnuti zmeni, vznikne nove ADR a stare se oznaci jako `Superseded`
- ADR se pouziva pro rozhodnuti s dlouhodobym dopadem, ne pro kazdy implementacni detail
- obecne architecture dokumenty popisuji aktualni cilovy stav; ADR vysvetluje, proc bylo rozhodnuti prijato

## Povinna metadata ADR

Kazde ADR ma na zacatku obsahovat:

```md
Status: Proposed | Accepted | Superseded | Deprecated
Date: YYYY-MM-DD
Decision owners: jmeno nebo role
Supersedes: ADR cislo nebo none
Superseded by: ADR cislo nebo none
```

Vyznam stavu:

- `Proposed` - rozhodnuti se posuzuje a zatim neni zavazne
- `Accepted` - rozhodnuti je platne a ma se podle nej implementovat
- `Superseded` - rozhodnuti bylo nahrazeno novejsim ADR
- `Deprecated` - rozhodnuti se nema pouzivat pro novou praci, ale nebylo nahrazeno jednim konkretnim ADR

## Doporucena struktura ADR

```md
# ADR 000X - Nazev

Status: Proposed
Date: YYYY-MM-DD
Decision owners: ...
Supersedes: none
Superseded by: none

## Kontext

## Rozhodnuti

## Dusledky

## Zamitnute alternativy

## Migracni nebo rollout plan
```

## Index

| ADR                                                                                                      | Nazev                                                  | Status   |
| -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | -------- |
| [`0001-python-backend.md`](0001-python-backend.md)                                                       | Python jako primarni backend                           | Accepted |
| [`0002-postgresql.md`](0002-postgresql.md)                                                               | PostgreSQL jako hlavni databaze                        | Accepted |
| [`0003-modular-monolith.md`](0003-modular-monolith.md)                                                   | Modularni monolit jako vychozi backendova architektura | Accepted |
| [`0004-read-models.md`](0004-read-models.md)                                                             | Oddeleni read modelu od canonical historie             | Accepted |
| [`0005-api-contract-generation.md`](0005-api-contract-generation.md)                                     | Generovani API kontraktu z OpenAPI                     | Accepted |
| [`0006-database-schema-migration.md`](0006-database-schema-migration.md)                                 | Prevod vlastnictvi DB schema z Prisma na Alembic       | Accepted |
| [`0007-python-credential-boundary.md`](0007-python-credential-boundary.md)                               | Python credential boundary a NextAuth session          | Accepted |
| [`0008-direct-twelve-data-fx.md`](0008-direct-twelve-data-fx.md)                                         | Prime FX z Twelve Data bez pivotu a fallbacku          | Accepted |
| [`0009-trading212-executed-trade-fx.md`](0009-trading212-executed-trade-fx.md)                           | Trading212 executed trade FX a oddeleni poplatku       | Accepted |
| [`0010-multi-currency-holding-cost-basis.md`](0010-multi-currency-holding-cost-basis.md)                 | Vice-menovy Holding cost basis                         | Accepted |
| [`0011-postgresql-backed-background-jobs.md`](0011-postgresql-backed-background-jobs.md)                 | PostgreSQL-backed background joby                      | Accepted |
| [`0012-derived-snapshot-rounding.md`](0012-derived-snapshot-rounding.md)                                 | Explicitni zaokrouhleni odvozenych snapshotu           | Accepted |
| [`0013-anycoin-btc-alias-onboarding.md`](0013-anycoin-btc-alias-onboarding.md)                           | Exactni onboarding Anycoin BTC aliasu                  | Accepted |
| [`0014-anycoin-btc-display-identity.md`](0014-anycoin-btc-display-identity.md)                           | Exactni zobrazovaci identita Anycoin BTC               | Accepted |
| [`0015-import-reconciliation-evidence-foundation.md`](0015-import-reconciliation-evidence-foundation.md) | Zaklad evidence importniho odsouhlaseni                | Accepted |

Status v tomto indexu se musi aktualizovat spolu se zmenou konkretniho ADR.
