# Epic: [název velké funkce]

## Výsledek a hranice

Popiš uživatelskou hodnotu, domény, vlastníka dat a jasně vyjmenuj, co epic nezahrnuje.

## Současný a cílový stav

Uveď současné Next.js/Python/DB hranice a cílové source of truth. Označ dočasné adaptéry a podmínky jejich odstranění.

## Neuzavřená rozhodnutí

API kontrakt, modulové hranice, schema/migration ownership, auth, peněžní invarianty, importní trust boundary, background jobs, idempotence, recovery a observabilita. Dlouhodobá rozhodnutí odkaž na ADR.

## Rizika

Bezpečnost/account isolation, ztráta dat, přesnost a měny, historické FX, zpětná kompatibilita, výkon/souběh, rollout a rollback.

## Rozpad na milestone a kroky

Každý krok zapisuj do tabulky:

| ID | Výsledek | Velikost/skóre | Závislosti | Riziko | Model | Ověření |
|---|---|---:|---|---|---|---|
| X.1 | [jedna schopnost] | M/6 | [ID] | střední | střední | [test] |

Pravidla pořadí: nejdřív uzavřít rozhodnutí; potom kompatibilní kontrakty; následně malé vertikální řezy; migrace/backfill odděleně; integrační a security testy; teprve nakonec odstranění staré cesty.

## Definition of Done epicu

- Všechny kroky mají splněná binární kritéria.
- Python/Next.js a Prisma/Alembic ownership jsou jednoznačné.
- Data migration, rollback/recovery a kompatibilita byly ověřeny.
- Auth, account isolation a finanční invarianty mají pozitivní i negativní testy.
- Dočasné adaptéry jsou odstraněné nebo mají konkrétní navazující krok.
