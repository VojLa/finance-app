# Documentation audit and gaps

Type: reference
Status: proposed
Owns: výchozí audit rozsahu pro návrh dokumentační migrace
Code: celé repository
Update when: před zahájením migrace nebo při přidání nového subsystému

## Prozkoumané vrstvy

- Next.js UI, serverové adaptéry a 18 adresářů pod `src/modules/`.
- FastAPI, auth a 25 modulů pod `backend/python/app/modules/`.
- PostgreSQL modely, Alembic migrace, schema artefakty a ownership manifest.
- Importní parsery, market providery, background jobs a recovery chování.
- Experimentální Rust engine bez runtime autority.
- Frontend, backend, databázové a dokumentační CI workflow.
- 83 frontendových/adaptérových a 253 Python testovacích souborů v aktuálním
  generovaném inventáři.
- `!docs`, `!planning`, `!user-docs`, `CHATGPT`, root a backend README.

Průchod je strukturální a kontraktní: určuje vlastnictví, entry points, datové
zdroje, testovací vrstvy a dokumentační pokrytí. Nenahrazuje budoucí
řádkový audit každého modulu při jeho konkrétní migraci.

## Co už funguje

- `!docs` má README síť, L0/L1 mapy a limit 500 řádků.
- Code, API, DB, module a test inventories vznikají deterministicky.
- CI kontroluje freshness, lokální odkazy a README v adresářích `!docs`.
- Doménové průvodce již rozlišují scope, autoritu a invarianty.
- `!planning`, `!docs` a `!user-docs` mají definovaný odlišný účel.

## Strukturální problémy

- Číslované složky, `domains/`, `architecture/modules/` a `domains/evidence/`
  tvoří paralelní cesty ke stejným informacím.
- `DOMAIN-MAP.md` je současně router i zkrácená doménová dokumentace.
- Účel, source of truth, invarianty a testy se opakují ve více souborech.
- Milestone a auditní evidence je místy vedena jako aktuální architektura.
- Jeden aktuální architecture evidence soubor má 498 řádků; mapa má 333.
- Dlouhé `CHATGPT/steps` a `CHATGPT/audits` nejsou oddělené od běžné navigace.
- `!user-docs` je zatím téměř prázdná kostra.

## Obsahové mezery

- jednotná testovací taxonomie a vazba invariant → testovací důkaz;
- stručná dokumentace DB ownershipu, migrací, driftu a obnovy;
- runbooky pro joby, importy, providery, migrace a snapshot/history recovery;
- stabilní katalog finančních, bezpečnostních a konzistenčních invariantů;
- explicitní mapa runtime modulů a povolených závislostí;
- jasné oddělení aktuálního kontraktu od auditní historie;
- human-readable adapter/API boundary bez kopírování OpenAPI;
- kontrola typu, vlastníka, stavu a aktualizačního triggeru dokumentu;
- sémantické user guides pro skutečně dostupné UI funkce.

## Testovací mezera

Projekt má široké testovací pokrytí, ale názvy `_integration`, marker
`pytest.mark.integration` a podmínka `skipif(DATABASE_URL)` nejsou používány
jednotně. Generovaný inventář umí vyjmenovat soubory, ale neříká, které riziko,
invariantu nebo recovery scénář test prokazuje. Chybí také jednotná klasifikace
frontend contract, view-model, boundary audit a E2E testů.
