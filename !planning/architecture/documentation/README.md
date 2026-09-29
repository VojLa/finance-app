# Documentation information architecture

Status: implemented V1

Tato složka zaznamenává implementovaný V1 dokumentační systém. Návrh vychází ze strukturálního průchodu kódem,
FastAPI routami, databázovými modely a migracemi, frontendem, testy, CI,
skripty a všemi dokumentačními kořeny.

## Čtecí pořadí

| Dokument                                            | Odpovídá na otázku                                      |
| --------------------------------------------------- | ------------------------------------------------------- |
| [Audit and gaps](audit-and-gaps.md)                 | Co projekt skutečně obsahuje a co v dokumentaci chybí?  |
| [Principles and network](principles-and-network.md) | Kdo vlastní informaci a jak jsou dokumenty propojené?   |
| [File type registry](file-types.md)                 | Jakou strukturu má každý typ souboru?                   |
| [Project coverage](project-coverage.md)             | Jak budou pokryté skutečné domény, moduly a testy?      |
| [Migration plan](migration-plan.md)                 | V jakém pořadí se bude dokumentace převádět a ověřovat? |

## Přijaté principy návrhu

- Jeden fakt má jednoho vlastníka; ostatní dokumenty na něj odkazují.
- `!docs`, `!planning`, `!user-docs`, historie a generated obsah se nemíchají.
- README je rozcestník, nikoli kontejner pro veškeré detaily.
- Úplné seznamy souborů, rout, modelů a testů generují skripty.
- Ruční dokumentace vysvětluje význam, hranice, invarianty, rizika a recovery.
- Kritická invarianta má stabilní ID, enforcement point a testovací důkaz.
- 500 řádků je nouzový hard limit; běžný ruční soubor má mít 40–200 řádků.

## Stav V1

Šablony, registry, reportovací kontroly a cílová dokumentační síť byly zavedeny.
Historické cesty zůstávají pouze jako kompatibilní rozcestníky; nový aktuální
obsah patří do sémantických cest pod `!docs/`. Další úpravy se řídí
[`!docs/development/documentation.md`](../../../!docs/development/documentation.md).
