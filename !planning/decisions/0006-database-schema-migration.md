# ADR 0006 - Prevod vlastnictvi DB schema z Prisma na Alembic

Status: Accepted
Date: 2026-07-16
Decision owners: VojLa
Supersedes: none
Superseded by: none

## Kontext

Soucasny fyzicky databazovy model je rizen pres Prisma. Cilovy backend je ale v Pythonu a ma pouzivat SQLAlchemy a Alembic. Dva migracni systemy nesmi dlouhodobe vlastnit stejne tabulky, protoze by vznikl konflikt, drift schema a nejasna odpovednost.

## Rozhodnuti

Prisma je docasny vlastnik existujiciho DB schema pouze po dobu hybridni migrace.

Cilovy stav:

- SQLAlchemy modely reprezentuji Python persistence vrstvu,
- Alembic je jediny vlastnik novych produkcnich migraci,
- Prisma nebude po dokonceni migrace menit tabulky vlastnene Python backendem,
- prechod musi zachovat existujici data a historii migraci.

## Dusledky

Pozitivni:

- jeden migracni source of truth v cilovem backendu,
- mensi riziko konfliktu schema,
- prirozena integrace s Python toolingem.

Negativni:

- migrace ownership vyzaduje opatrny cutover,
- behem prechodne faze musi byt jasne, ktery system vlastni kterou zmenu,
- existujici Prisma migrace se nesmi bezduvodne prepisovat.

## Zamitnute alternativy

- dlouhodobe provozovat Prisma a Alembic nad stejnymi tabulkami,
- ponechat Prisma jako migracni system pro Python backend,
- zahodit existujici databazi a vytvorit ji bez migrace znovu.

## Migracni nebo rollout plan

1. Zmapovat existujici Prisma schema a migrace.
2. Vytvorit odpovidajici SQLAlchemy modely.
3. Vytvorit Alembic baseline odpovidajici realnemu produkcnimu schema.
4. Overit baseline na kopii databaze a v testovacim prostredi.
5. Oznacit okamzik cutoveru, od ktereho nove migrace vytvari pouze Alembic.
6. Po dokonceni migrace odstranit Prisma z cilove backendove architektury.
