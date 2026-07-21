# [ID] – [Název implementačního kroku]

## Metadata

- Epic/milestone:
- Velikost a skóre:
- Doporučený model:
- Owner/source of truth:

## Cíl

Jednou větou popiš pozorovatelný výsledek.

## Kontext k načtení

- Povinně `AGENTS.md`.
- Relevantní `memory/...`, `!planning/...` a konkrétní zdrojové soubory.
- Nenačítej celý repozitář bez odůvodnění.

## Současný stav

Co existuje, kde je chování implementované a jaký problém zůstává.

## Rozsah

- [ ] Jedna konkrétní změna chování.
- [ ] Nutné testy a dokumentace.

## Mimo rozsah

- Žádný nesouvisející refaktoring.
- Žádný další endpoint/funkce/migrace bez explicitního uvedení.

## Požadované chování

1. Happy path:
2. Chyby a hraniční stavy:
3. Autorizace/account isolation:
4. Idempotence/souběh/rollback:
5. Peníze, měna a zaokrouhlení:

## Návrh řešení

Popiš tok FastAPI/Pydantic → application/service → repository/SQLAlchemy → PostgreSQL a odpovědnost vrstev. Pokud návrh není uzavřený, nejdřív použij `PLAN.md`.

## Databáze a kontrakty

Uveď migration owner, případnou Prisma migraci či důvod, proč schéma neměníme. Alembic použij jen po explicitním cutoveru. Popiš API/OpenAPI kompatibilitu.

## Bezpečnost

Chráněné aktivum, oprávněné role, validace nedůvěryhodného vstupu, zakázaná logovaná data a negativní test.

## Akceptační kritéria

- [ ] Binární, samostatně ověřitelné podmínky.
- [ ] Testy dokazují správné chování i zamítnutí cizího přístupu.
- [ ] Diff neobsahuje změny mimo rozsah.

## Ověření

Uveď nejmenší relevantní test a následnou quality gate. Po implementaci vrať výstup podle `IMPLEMENTATION-OUTPUT.md`.
