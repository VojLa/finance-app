# Workflow od návrhu po kontrolu

## 1. Zúžení požadavku

- Urči viditelný výsledek, dotčenou doménu a uživatele.
- Vyjmenuj, co je mimo rozsah.
- Najdi 3–8 nejrelevantnějších souborů; neposílej modelu celý repozitář.
- Klasifikuj bezpečnost, finanční výpočty, API kontrakt a databázový dopad.

## 2. Velikost a plán

Zařaď změnu podle `STEP-SIZING.md`. XS/S může jít přímo do implementace. M potřebuje krátký plán, pokud prochází více vrstvami. L se nejdřív rozpadá. XL není implementační krok.

Plán je povinný, když se mění modulová hranice, veřejné API, source of truth, auth/autorizace, peněžní invariant, migrace, importní trust boundary nebo recovery postup. Dlouhodobé rozhodnutí patří také do `!planning/decisions/`.

## 3. Implementace malého vertikálního řezu

Preferovaný řez je jedna schopnost napříč nutnými vrstvami: FastAPI endpoint → Pydantic kontrakt → application/service → SQLAlchemy repository/model → testy. HTTP vrstva zůstává tenká; business pravidla nepatří do routeru. Nevytvářej prázdné vrstvy jen kvůli šabloně.

Pravidla:

- žádný nesouvisející refaktoring;
- maximálně jedna nezávislá změna chování;
- autorizace a account isolation se ověřují na backendu;
- peníze nikdy jako `float`; používej `Decimal` a explicitní měnu i pravidla zaokrouhlení;
- importy a externí data jsou nedůvěryhodné vstupy;
- citlivá finanční data, tokeny a raw importy se nelogují;
- transakční hranice, idempotence a souběh musí být explicitní.

## 4. Databázové pravidlo

Než vznikne změna schématu, ověř `backend/python/database/schema_ownership.toml` a aktuální plán migrace. V současném hybridním stavu vlastní aplikační migrace Prisma. Nevytvářej aktivní Alembic revizi ani nepřeváděj ownership bez explicitně schváleného cutoveru. Neupravuj staré Prisma migrace a nespouštěj schema create/stamp/upgrade při startu aplikace.

## 5. Testy a automatické kontroly

Začni nejmenší relevantní sadou testů, potom spusť přiměřenou quality gate.

Python backend (z `backend/python`):

~~~bash
uv run pytest <relevantní-test>
uv run ruff check .
uv run ruff format --check .
uv run mypy app scripts tests
uv run pytest
~~~

Úplná backendová brána: `uv run python scripts/check.py`. Pro TypeScript podle rozsahu použij `npm.cmd test`, `npm.cmd run lint` a `npx.cmd tsc --noEmit`. `npm run build` nespouštěj, pokud běží `next dev`.

Testy musí podle rizika pokrýt happy path, neplatný vstup, cizí účet, nedostatečnou roli, rollback, opakování/idempotenci, souběh a přesnost peněz. Změna API vyžaduje contract/OpenAPI test; oprava parseru regression fixture.

## 6. Review a dokončení

Nech zkontrolovat pouze diff a zadání. Nejdřív řeš správnost, bezpečnost, ztrátu dat a kontrakty; až potom styl. Krok je hotový, když splňuje binární akceptační kritéria, relevantní kontroly prošly, diff neobsahuje změny mimo rozsah a dokumentace/ADR odpovídají skutečnosti.
