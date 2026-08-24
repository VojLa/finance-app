# Documentation file type registry

Type: reference
Status: proposed
Owns: povinnou strukturu jednotlivých typů dokumentů
Code: `!docs`, `!planning`, `!user-docs` a historie
Update when: vznikne nový typ informace nebo se změní jeho vlastník

## README rozcestník

Obsahuje rozsah adresáře, tabulku dokument → kdy jej číst, odkaz na rodiče a
pravidlo, co sem nepatří. Neobsahuje dlouhé invarianty, file list ani milestone
historii. Aktualizuje se při přidání, odstranění nebo změně účelu potomka.

## L0 Project Map

Obsahuje runtime vrstvy, autority, hlavní domény a čtecí cestu. Neobsahuje
konkrétní testy ani detailní entry points. Mění se jen při změně systémové
hranice, autority nebo seznamu domén.

## L1 Domain Map

Jeden řádek pro každou doménu: `ID`, účel, source of truth, hlavní vstup, přímé
závislosti a doménový dokument. Detail souborů a testů patří jinam.

## Domain README

Povinné sekce:

1. účel a hranice;
2. source of truth a odvozená data;
3. veřejné schopnosti;
4. vlastněné runtime moduly;
5. vstupní a výstupní závislosti;
6. odkazy na invarianty, flows, API, data, test matrix a runbooky;
7. omezení aktuální implementace.

Nekopíruje přesné invarianty, úplný seznam endpointů, tabulek, testů ani budoucí
roadmapu. Aktualizuje se při změně významu nebo hranice domény.

## Module card

Vzniká pouze pro skutečný runtime modul s vlastním pravidlem, stavem nebo
hranicí. Obsahuje odpovědnost a non-goals, entry points, existující vrstvy,
čtená/zapisovaná data, povolené závislosti, transakční/auth/concurrency hranici
a odkazy na invarianty a cílené testy. Nepopisuje každou funkci ani úplný file
list. Čistý adapter bez vlastní odpovědnosti zůstává jen v inventory.

## Flow dokument

Popisuje jeden end-to-end tok přes více modulů. Obsahuje trigger, ukončovací
podmínku, očíslované kroky s vlastníkem, předávaná data, trust a transaction
boundaries, failure/retry/idempotence/recovery a integrační důkazy. Příklady:
import publication, snapshot refresh, portfolio history rebuild a login bridge.

## Invariant dokument

Vlastní jednu úzce související rodinu drahých pravidel. Každá invarianta má:

- stabilní ID a přesné tvrzení;
- rozsah a source of truth;
- enforcement point;
- failure behavior;
- reprezentativní testovací důkaz.

Patří sem peněžní přesnost, měny, FX, canonical lineage, idempotence, publication
fencing, account isolation, auth a ochrana citlivých dat.

## API a contract dokument

Ruční část vlastní auth, error envelope, decimal wire format, pagination,
versioning a adapter boundary. Endpointy, request/response modely a schemas
generuje OpenAPI inventory. Doména na operace pouze odkazuje.

## Data a persistence dokument

Ruční část vlastní databázovou autoritu, model ownership, transakční pravidla,
migrace, retention a recovery. Tabulky, enumy, sloupce a revize jsou generované.
Doména vysvětluje význam dat, nikoli fyzické schema.

## Test strategy

`testing/strategy.md` definuje vrstvy a co každá dokazuje. Taxonomie rozlišuje:

- unit a pure calculation;
- service/repository component;
- HTTP/OpenAPI contract;
- PostgreSQL integration a migration;
- provider/parser fixture a parity;
- end-to-end business flow;
- concurrency, retry, recovery a idempotence;
- architecture/boundary audit;
- frontend view-model a UI interaction.

## Quality gates

`testing/quality-gates.md` vlastní přesné lokální a CI příkazy, předpoklady,
progressive testing pořadí a pravidla pro full gate. Příkazy se nekopírují do
každé domény.

## Domain test matrix

`domains/<domain>/testing.md` má sloupce `Risk ID`, `Invariant`, `unit`,
`contract`, `integration`, `E2E/recovery`, `fixture` a `gap`. Uvádí
reprezentativní suite nebo pattern, ne úplný seznam testů. Úplný seznam zůstává
v generated `TEST-INVENTORY.md`.

## Runbook

Obsahuje preconditions, ochranu dat, příkazy, očekávané důkazy,
rollback/recovery a eskalační podmínku. Neobsahuje architektonické zdůvodnění.
Minimální runbooky: schema migration/drift, import/job recovery, provider alias
onboarding, snapshot/history rebuild a bezpečná incidentní diagnostika.

## ADR

Obsahuje context, decision, alternatives, consequences, rollout a supersession.
Vlastní důvod a trade-off, nikoli implementační deník. Aktuální dokumentace
popisuje platný dopad a pouze odkazuje na ADR.

## Historical evidence

Obsahuje `Status: historical`, datum, scope, commit/revizi, provedené kontroly,
výsledek a odkazy na aktuální pravidla. Audit a milestone closure nejsou zdrojem
aktuální architektury ani povinnou četbou běžného úkolu.

## User guide

Obsahuje cíl uživatele, předpoklady, postup v UI, význam hodnot, očekávaný
výsledek, chyby a související návody. Neobsahuje repository/service třídy,
tabulky ani interní endpointy.

## Generated inventory

Uvádí generator, zdroj dat a příkaz k obnově. AI jej negeneruje ani ručně
neupravuje. Velký inventář se dělí deterministicky podle vrstvy či domény a
hlavní soubor zůstává krátkým indexem.
