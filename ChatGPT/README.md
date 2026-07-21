# Společný vývoj finance-app s AI

Tato složka je praktický rozcestník pro návrh, implementaci a kontrolu malých změn s co nejnižší spotřebou kreditů. Nenahrazuje `AGENTS.md`, `memory/` ani architekturu v `!planning/`; šablony na ně odkazují a doplňují je.

## Základní princip

> Silný model rozhoduje jen tam, kde je rozhodnutí drahé nebo rizikové. Běžná implementace pracuje s úzkým kontextem a automatické nástroje ověřují vše, co lze ověřit deterministicky.

## Dokumenty

- [WORKFLOW.md](WORKFLOW.md) – cesta od požadavku po merge.
- [STEP-SIZING.md](STEP-SIZING.md) – velikosti XS až XL a pravidla dělení.
- [MODEL-SELECTION.md](MODEL-SELECTION.md) – volba modelu a eskalace.
- [templates/STEP.md](templates/STEP.md) – zadání jednoho implementačního kroku.
- [templates/PLAN.md](templates/PLAN.md) – návrh řešení bez implementace.
- [templates/IMPLEMENTATION-OUTPUT.md](templates/IMPLEMENTATION-OUTPUT.md) – povinný výstup implementace.
- [templates/REVIEW.md](templates/REVIEW.md) – kontrola diffu.
- [templates/BUGFIX.md](templates/BUGFIX.md) – lokalizovaná oprava chyby.
- [templates/EPIC.md](templates/EPIC.md) – rozpad velké funkce.

## Rychlé použití

1. Velký požadavek rozpadni pomocí `templates/EPIC.md`.
2. Jeden krok zapiš podle `templates/STEP.md`; preferuj velikost S nebo M.
3. Pokud existuje nejasné rozhodnutí, nejdřív použij `templates/PLAN.md`.
4. Implementaci omez na relevantní soubory a požaduj výstup dle `templates/IMPLEMENTATION-OUTPUT.md`.
5. Spusť projektové kontroly a modelu dej ke kontrole jen diff přes `templates/REVIEW.md`.

## Povinný kontext finance-app

Před prací vždy přečti `AGENTS.md`. Podle oblasti načti jen relevantní dokumenty z `memory/` a `!planning/`. U Python backendu respektuj `backend/python/README.md`. Databázový ownership se nesmí domýšlet: aktuálně PostgreSQL schéma vlastní Prisma, SQLAlchemy je runtime/verifikační zrcadlo a Alembic je připravený na budoucí explicitní cutover.
