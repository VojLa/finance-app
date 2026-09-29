# Audit aplikace Finance App — 28. 9. 2026

Type: historical
Status: audit evidence; findings not implemented
Scope: lokální pracovní strom a běžící vývojové kontejnery, nikoli certifikace produkce
Git base: `92f5059`, větev `remediation/0.1-r10e2-canonical-current-money`; více než 500 již existujících změněných/nezařazených cest

## 1. Report současného stavu aplikace

### Závěr a rozsah ověření

Aplikace má použitelný technický základ, ale nyní ji nelze považovat za spolehlivou osobní finanční evidenci. Kritické problémy jsou na rozhraních mezi importem, publikací snapshotů, workery a UI. Nejde pouze o pomalý Python nebo o chybějící aliasy aktiv.

Databázová část přechodu na čtyři snapshotové projekce existuje: `AccountSnapshot`, `InvestmentAccountSnapshot`, `PortfolioSnapshot`, `NetWorthSnapshot`. V živém schématu nezůstaly tabulky `PortfolioHistory*`. To ale není důkaz dokončeného funkčního přechodu: zveřejňování a čtení historie má níže doložené chyby.

Prověrka zahrnovala zdrojový kód hlavních procesů, cílené testy, autorizované read-only HTTP požadavky přes Next.js i přímo Python API, read-only SQL a profilování databázových dotazů. Neproběhl nový import, změna hesla, změna členství, reset databáze ani oprava runtime kódu. Nezávislé dílčí kontroly provedli Terra a Sol; konečné zařazení nálezů vlastní hlavní auditor.

Limity: neprovedl jsem destruktivní ani zápisové end-to-end scénáře na uživatelově DB, plný penetrační test, všechny externí providery ani produkční zátěžový test. Prohlížeč ověřil přesměrování nepřihlášeného návštěvníka na přihlášení; přihlášené cesty byly ověřovány HTTP diagnostikou a kódem, nikoli kompletním klikacím průchodem. Neprověřenou cestu neoznačuji za bezchybnou.

Závažnost: P1 = zásadní blokace, únik nebo nesprávná finanční prezentace; P2 = důležitá dílčí chyba. „Potenciální“ znamená konkrétní riziko z kódu bez prokázání příslušné situace v běžícím účtu.

### Zamezuje funkčnosti

#### F01 — P1: API grafu selhává na přesnosti částek

- Reprodukce: autorizované `/api/v1/portfolio/history?range=ALL`, `range=1Y` a účetní varianta pro Trading vracejí HTTP 500. Přes frontend se chyba mění na obecnou nedostupnost Python API.
- Konkrétní nalezené pole: `history.points[0].investment_by_currency[0].value` má deset desetinných míst. Odpověď ho serializuje jako peněžní hodnotu se šesti místy; striktní serializátor odmítne ztrátu přesnosti.
- Nejde o nedostupný server: jiné autorizované endpointy současně vracejí 200.
- Oprava: sladit typ původních měnových hodnot mezi uloženými daty, Python odpovědí a TS validátorem. Zaokrouhlení musí být výslovné finanční pravidlo, ne skryté potlačení výjimky při čtení.
- Důkaz: [history_api_models.py:21](D:/Programing/finance-app/backend/python/app/modules/portfolio_snapshot/history_api_models.py:21), [history_reader.py:69](D:/Programing/finance-app/backend/python/app/modules/portfolio_snapshot/history_reader.py:69), [numeric_serialization.py:31](D:/Programing/finance-app/backend/python/app/shared/numeric_serialization.py:31).

#### F02 — P1: Pravidelná obnova skryje celou dosavadní historii

- Pětiminutová obnova publikuje novou generaci obsahující jediný současný časový bod. Reader grafu čte pouze generaci aktuálního uživatelského ukazatele.
- V DB hlavního uživatele existují starší publikované generace s 1 458 body od roku 2019. Během auditu aktuální publikace obsahovala jediný bod z dnešního dne.
- Starší body nejsou smazané, ale nejsou z aktuálního grafu dostupné. Samotná oprava HTTP 500 tudíž graf nevyřeší.
- Oprava: každá publikace musí zachovat úplnou zamýšlenou snapshotovou časovou řadu; aktualizace současného bodu nesmí publikovat neúplnou náhradu. Zachovat atomický uživatelský manifest, ne obnovovat samostatnou finanční historii vedle snapshotů.
- Důkaz: [scheduled_runner.py:115](D:/Programing/finance-app/backend/python/app/modules/snapshot_refresh/scheduled_runner.py:115), [executor.py:642](D:/Programing/finance-app/backend/python/app/modules/snapshot_refresh/executor.py:642), [history_reader.py:151](D:/Programing/finance-app/backend/python/app/modules/portfolio_snapshot/history_reader.py:151).

#### F03 — P1: Opuštěné rozpracované generace blokují plánovač historie

- U hlavního uživatele je pět generací ve stavu `staged`, vytvořených 4. září. Není aktivní rebuild job; existuje sedm neúspěšných a jeden dokončený rebuild.
- Plánovač je zapnutý, ale `next_capture_at` zůstal na 4. září 19:30 UTC. Neexistuje dirty stav, který by toto vysvětloval jako čekání na novou změnu.
- Scheduler považuje libovolnou `staged` generaci uživatele za probíhající stavbu a vrátí `deferred_building`. Nekontroluje živý job/lease ani stáří této generace.
- Oprava: explicitní životní cyklus rozpracované generace, bezpečné rozlišení živé a opuštěné práce, uzavření/fencing při terminálním selhání a řízené zotavení již blokovaných uživatelů. Nestačí restart procesu ani reset počtu pokusů. Samotné obnovení plánování nevyžaduje okamžité mazání starých rozpracovaných řádků; případný cleanup je samostatně ověřovaný krok.
- Důkaz: [scheduler/repository.py:104](D:/Programing/finance-app/backend/python/app/modules/portfolio_history/scheduler/repository.py:104), [scheduler/service.py:116](D:/Programing/finance-app/backend/python/app/modules/portfolio_history/scheduler/service.py:116), [jobs/worker.py:180](D:/Programing/finance-app/backend/python/app/modules/portfolio_history/jobs/worker.py:180).

#### F04 — P1: FE a BE nesouhlasí na rozlišení grafu

- Python vrací pro minutový snapshot rozlišení `1`, pro hodinový `60`. TS validátor přijímá starý pevný seznam začínající 30, 120, 360…; obě uvedené hodnoty odmítne.
- Izolovaná kontrola minutové odpovědi skončila `Snapshot portfolio history has an incompatible contract`.
- Server navíc pro přepočtenou řadu odvozuje rozlišení ze vzdáleností již vybraných bodů; není tím zaručena shoda s pevným seznamem. Coverage se musí ověřit společně s downsamplingem, nikoli pouze rozšířit dvě čísla v seznamu.
- Oprava: jeden veřejný kontrakt odpovídající skutečné snapshotové řadě a kontraktový test skutečného Python JSON přes TS parser.
- Důkaz: [history_reader.py:61](D:/Programing/finance-app/backend/python/app/modules/portfolio_snapshot/history_reader.py:61), [snapshot-history-contract.ts:74](D:/Programing/finance-app/src/modules/portfolio/snapshot-history-contract.ts:74).

#### F05 — P1/P2: Souběh obnovy a historického jobu nemá uzavřené zotavení

- Z kódu plyne závod: po výběru uživatelů pro refresh může začít historický capture. Novější refresh se publikuje dříve a jeho kauzální watermark odmítne starší capture.
- Automatický retry používá tentýž job a původní `created_at`, takže takto zastaralý job nemůže watermark předběhnout ani v dalším pokusu.
- Druhý závod: historie se již publikuje, refresh mezitím změní ukazatel a finalizace historie odmítne vlastní dokončenou publikaci, protože již není aktuální.
- Tato větev je doložena kódem, nikoli experimentálním vyvoláním na živých datech. Neoznačuji ji automaticky za příčinu všech sedmi uložených selhání.
- Oprava: koordinovat obě publikace, odlišit dokončenou/zastaralou/obnovitelnou práci a pro zastaralou práci vytvořit nový odpovídající job. Neměnit svévolně čas starého jobu a tím neporušit audit/idempotenci.
- Důkaz: [series_persistence.py:455](D:/Programing/finance-app/backend/python/app/modules/snapshot_refresh/series_persistence.py:455), [scheduler/service.py:171](D:/Programing/finance-app/backend/python/app/modules/portfolio_history/scheduler/service.py:171), [builder/executor.py:379](D:/Programing/finance-app/backend/python/app/modules/portfolio_history/builder/executor.py:379).

#### F06 — P1 použitelnosti: Provozní dashboard tráví přes šest sekund jedním SQL dotazem

- Tři čtení služby: 8 313 / 6 457 / 6 232 ms. Dotaz na posledních šest transakcí: 7 550 / 6 283 / 6 094 ms.
- `EXPLAIN ANALYZE`: 6 235 ms celkem; z toho přibližně 6 012 ms kompilace/optimalizace SQL pomocí PostgreSQL JIT. Dotaz vytváří množství souvisejících poddotazů pro viditelnost a evidenci transakcí.
- Kontrolní měření s JIT vypnutým pouze v jedné diagnostické transakci: 374 / 215 / 217 ms. Nastavení aplikace ani DB jsem nezměnil.
- Oprava: zjednodušit dotaz a dávkově vyhodnocovat publikovanou evidenci, zvolit indexy podle plánu; lokální vypnutí JIT může být cílená provozní pomoc, není samo o sobě dosažením 100 ms.
- Důkaz: [operational_dashboard/repository.py:65](D:/Programing/finance-app/backend/python/app/modules/operational_dashboard/repository.py:65), [operational_visibility.py](D:/Programing/finance-app/backend/python/app/modules/transactions/operational_visibility.py).

#### F07 — P2: „Nic se nezměnilo“ se převádí na chybu

- Python správně vrací 204 pro shodnou publikační verzi. Společný transport ale před předáním odpovědi vyžaduje JSON content-type.
- Ověřeno přes Next API: dotaz se známou verzí vrací 502. Větev pro 204 v route se tak vůbec neuplatní.
- Změněná verze s odpovědí 200 fungovat může; neznamená to úplnou nefunkčnost všech aktualizací.
- Oprava: explicitně podpořit prázdné úspěšné odpovědi a otestovat kompletní trasu, nikoli jen mock route.
- Důkaz: [transport.ts:72](D:/Programing/finance-app/src/modules/python-api/server/transport.ts:72), [read-model-version/route.ts:33](D:/Programing/finance-app/src/app/api/read-model-version/route.ts:33).

#### F08 — P2: Obnova a chyby UI nejsou konzistentní

- Dashboard načte provozní přehled pouze při vstupu. Tlačítko Aktualizovat, dokončení importu i změna verze obnovují jen finanční část; příjmy, výdaje a rozpočty mohou zůstat staré. [dashboard/page.tsx:110](D:/Programing/finance-app/src/app/dashboard/page.tsx:110).
- Transakce nemají při načítání `catch/finally`; selhání může nechat nekonečné načítání. Starší odpověď může přepsat novější filtr. [transactions/page.tsx:295](D:/Programing/finance-app/src/app/transactions/page.tsx:295).
- Obdobný závod existuje u seznamu účtů a přepínání měsíců rozpočtu. [accounts/page.tsx:104](D:/Programing/finance-app/src/app/accounts/page.tsx:104), [budget/page.tsx:50](D:/Programing/finance-app/src/app/budget/page.tsx:50).
- Selhání kategorií se tváří jako prázdný seznam; chyba síťového požadavku při změně hesla může ponechat formulář zablokovaný. [categories/page.tsx:149](D:/Programing/finance-app/src/app/categories/page.tsx:149), [settings/page.tsx:69](D:/Programing/finance-app/src/app/settings/page.tsx:69).
- Oprava: oddělit loading/empty/error/stale, ignorovat zastaralé odpovědi a aktualizovat všechny dotčené sekce.

### Správnost a důvěryhodnost finančních údajů

#### D01 — P1: Nově vytvořený snapshot se vydává za novou cenu

- Publikované portfolio i dashboard nastavují `valuationTimestamp` na čas snapshotu, nikoli na čas cenové evidence.
- Při živém měření byla odpověď oceněna údajně v 18:39 UTC a `isStale=false`, přesto obsahovala cenu z 15:30 UTC.
- Writer navíc pro souhrnný čas používá nejnovější (`max`) cenu. Jedna čerstvá pozice proto může zastínit zastaralé ostatní pozice. Je třeba jednoznačně definovat stáří všech požadovaných price/FX vstupů.
- Oprava: oddělit čas publikace, čas snapshotu a skutečné stáří ocenění. Upozornit na zastaralé vstupy podle schválené 30minutové politiky; zachovat poslední známé částky.
- Důkaz: [published_snapshot/api.py:150](D:/Programing/finance-app/backend/python/app/modules/published_snapshot/api.py:150), [writer.py:304](D:/Programing/finance-app/backend/python/app/modules/portfolio_snapshot/writer.py:304).

#### D02 — P1 podmíněný kontraktem: Historický výběr může obsahovat dnešní rozpad měn

- Při připnutém historickém bodu UI používá jeho měnové rozpady, ale při chybějícím volitelném poli doplní současný `view.summary`.
- Současný reader obvykle posílá pole, takže tento scénář není dokladem konkrétního chybného zůstatku v dnešní odpovědi. Veřejný kontrakt však absenci dovoluje a kód pak prokazatelně směšuje dva časy.
- Oprava: v historickém režimu buď historická hodnota, nebo výslovná nedostupnost; nikdy současná náhrada.
- Důkaz: [portfolio/page.tsx:339](D:/Programing/finance-app/src/app/portfolio/page.tsx:339).

#### D03 — P2, reprodukovaná krajní chyba Anycoin parseru

- Nepřiměřeně dlouhé TX ID se místo chyby zahodí jako chybějící. Dva různé vklady se shodným časem, měnou a částkou pak dostanou stejný náhradní deduplikační klíč.
- Izolovaná reprodukce se dvěma odlišnými ID délky 10 001 znaků vytvořila dva postovatelné řádky se shodným klíčem; deduplikace jeden označí za duplicitu.
- Není doloženo, že takto vypadá uživatelův běžný export nebo že právě toto způsobilo předchozí neúspěšný import.
- Oprava: odlišit chybějící a neplatný identifikátor; neplatný řádek předat k revizi, nevytvářet za něj heuristickou identitu.
- Důkaz: [anycoin.py:57](D:/Programing/finance-app/backend/python/app/modules/imports/anycoin.py:57), [anycoin.py:273](D:/Programing/finance-app/backend/python/app/modules/imports/anycoin.py:273), [deduplication.py:230](D:/Programing/finance-app/backend/python/app/modules/imports/deduplication.py:230).

#### D04 — P2: Některé obrazovky dovolují zavádějící klasifikaci

- Uživatel může změnit typ kategorie na příjem, i když už má navázané výdajové transakce; jejich kompatibilita se znovu neověří. [categories/service.py:93](D:/Programing/finance-app/backend/python/app/modules/categories/service.py:93).
- Souhrnné portfolio správně skrývá nedostupný souhrnný koláč, ale tabulka stále nazývá procenta jednotlivých účtů pouze „Alokace“. Nejde o prokázanou chybu součtu peněz; procenta potřebují jasný jmenovatel. [SnapshotHoldingsTable.tsx:62](D:/Programing/finance-app/src/modules/portfolio/SnapshotHoldingsTable.tsx:62).

### Hrozba kybernetická — neoprávněný přístup

#### S01 — P1: Odebrané sdílení se nepromítne do uloženého rozpočtu

- Rozpočet používá uložené vazby na účty. Pokud existují, znovu nekontroluje současné členství a dotaz na výdaje neobsahuje uživatele.
- Po odebrání člena tak jeho dříve uložený rozpočet může dál ukazovat výdaje sdíleného účtu za odpovídající měsíc/kategorii. Odebrání členství tyto vazby neodstraní.
- Ověřeno kódem a izolovaným fake-repository testem bez přístupu do DB: odebraný účet se dostal do dotazu i výsledku, kontrola aktuálního členství nebyla zavolána.
- Oprava: každé čtení omezit aktuálními oprávněními; samotné odstraňování pomocných vazeb nestačí jako bezpečnostní hranice.
- Důkaz: [budgets/service.py:254](D:/Programing/finance-app/backend/python/app/modules/budgets/service.py:254), [budgets/repository.py:126](D:/Programing/finance-app/backend/python/app/modules/budgets/repository.py:126), [accounts/service.py:264](D:/Programing/finance-app/backend/python/app/modules/accounts/service.py:264).

#### S02 — P1 při dosažitelnosti ze sítě: Vývojové API a DB jsou zbytečně vystavené

- Běžící Docker publikuje porty 3000, 8010 a 5433 na všech rozhraních, nikoli jen loopbacku.
- Interní podpisový klíč API se v běžícím prostředí shoduje s veřejně uloženou vývojovou konstantou. Kdo dosáhne na API a zná identitu uživatele, může tento klíč zneužít k napodobení interní autentizace.
- DB používá vývojové přihlašovací údaje a runtime aplikace se připojuje jako databázový superuser.
- Skutečná dostupnost z internetu/LAN závisí na firewallu a tunelu; nebyla zvenčí testována. Nejde o tvrzení, že už došlo k napadení. Skutečný NextAuth session secret se s vývojovou výchozí hodnotou neshodoval.
- Oprava: privátní API/DB síť, pro lokální přístup nejvýše loopback; náhodný interní klíč, odmítání známých vývojových klíčů mimo lokální režim a omezená DB role.
- Důkaz: [docker-compose.yml](D:/Programing/finance-app/docker-compose.yml).

#### S03 — P1 před síťovým nasazením: Zranitelné knihovny

- Poslední `npm audit --omit=dev` hlásil 7 zasažených balíčků: 1 critical, 4 high, 1 moderate, 1 low. Nejde o sedm prokázaných cest k napadení této aplikace.
- Běžící Next.js je 15.5.21. Bezpečnostní opravy relevantních advisory začínají v řadě 15.5 na 15.5.24; audit nabízí kompatibilní aktualizaci 15.5.26.
- Kritický Windows-hosted problém není potvrzenou cestou v současném Linux kontejneru. AVIF/image-optimization problém vyžaduje dosažitelnou cestu pro zpracování škodlivého obrázku; exploitability této cesty jsem neprokazoval.
- Oprava: aktualizovat lockfile i případné overrides, znovu postavit obrazy a otestovat aktuálně skutečně nainstalované balíčky.
- Primární zdroje: [Next.js Windows advisory](https://github.com/vercel/next.js/security/advisories/GHSA-p293-qw3h-jr36), [Next.js AVIF advisory](https://github.com/vercel/next.js/security/advisories/GHSA-2xp9-vwfh-vxw4), [sharp advisory](https://github.com/lovell/sharp/security/advisories/GHSA-rgj7-g3m4-5g8c).

#### S04 — P2 a otevřené bezpečnostní ověření

- Změna hesla mění pouze hash; již existující JWT relace nejsou odvolány. Je nutná verze relace nebo jiný mechanismus revokace. [auth/service.py:115](D:/Programing/finance-app/backend/python/app/auth/service.py:115), [src/lib/auth.ts:24](D:/Programing/finance-app/src/lib/auth.ts:24).
- V prověřených veřejných registračních/přihlašovacích cestách není aplikační rate limit. Případná ochrana před aplikací nebyla ověřena; jde o otevřený bod, ne prokázané prolomení hesla.
- Transakční repository některé cesty neomezuje na přijaté členství (`accepted_at`). Běžná cesta pozvánky ale vytvoří člena až při přijetí. Jde o nekonzistentní invariant vyžadující test, nikoli prokázaný útok pouhou neodsouhlasenou pozvánkou. [transactions/repository.py:146](D:/Programing/finance-app/backend/python/app/modules/transactions/repository.py:146).

### Zamezuje dalšímu vývoji nebo jej omezuje

#### V01 — P2: Runtime prostředí není reprodukovatelné a je částečně zastaralé

- Python Dockerfile instaluje volné závislosti přes `pip install -e .[dev]`, ale CI používá `uv sync --frozen`. Existující `uv.lock` se tak v kontejneru nerespektuje.
- Backendový kód je připojen jako aktuální adresář, zatímco workflow a část kořenových souborů jsou starší kopie v image.
- Konkrétní následek: `database_migrate.py check` v běžícím kontejneru selhal na kontrole CI artefaktu. Hostitelský workflow obsahuje pět kontrol aktuálního headu, image nula a pět kontrol staršího `3z0001historydrop`.
- Přímý Alembic check a samostatné porovnání SQLAlchemy se živým DB schématem prošly. Není to důkaz poškozeného DB schématu, ale rozpor verze běžícího balíku a zdrojů.
- Oprava: sjednotit zamčené závislosti a skladbu runtime/migračního obrazu, zaznamenat verzi artefaktu a ověřovat ji při nasazení.
- Důkaz: [backend/python/Dockerfile](D:/Programing/finance-app/backend/python/Dockerfile), [migration_policy.py:1201](D:/Programing/finance-app/backend/python/scripts/migration_policy.py:1201).

#### V02 — P2: Kontroly nejsou zelené a nechrání celý tok

- TypeScript typy a ESLint prošly. Kompletní frontend suite: 645 passed, 3 failed, 5 skipped. Dvě selhání jsou křehké kontroly zdrojového textu/hashů; třetí časový limit mezi runtime při samostatném opakování prošel (11/11).
- Python Ruff prošel. Mypy hlásí 61 chyb v 16 souborech z 328 kontrolovaných.
- Importní sada: 188 passed, 1 skipped, 1 konfigurační error kvůli zděděnému zapnutí history runtime bez DB URL. Tento konkrétní test při vypnutých runtime flagách prošel.
- Cílená sada snapshotů/historie/auth/rozpočtů: 210 passed, 4 skipped. Transakční/category modely: 7 passed. Cílené frontend importní sady: 21 + 28 passed (jde o podmnožiny frontendových testů, nikoli další celkový počet).
- Žádná z těchto zelených dílčích sad nezabránila F01–F04 nad aktuálně uloženými daty. Je potřeba doplnit testy propojených hranic, ne pouze přepsat očekávané hashe.

#### V03 — P2: Vedle publikovaného čtení zůstává stará živá cesta

- `/portfolio/current` a `/dashboard/current` jsou stále registrované. Jejich služba může získávat provider evidence během requestu.
- Konstrukce odpovědí zároveň nevyplňuje nová povinná pole `valuation_timestamp` a `is_stale`; statická kontrola konstruktoru proti Pydantic modelu potvrdila obě chybějící pole.
- Současná hlavní FE snapshotová cesta tyto staré endpointy nepoužívá. Je to ale rozbitá a architektonicky nejednoznačná veřejná API větev.
- Oprava: výslovně rozhodnout o jejím odstranění/deprecaci nebo kompatibilní implementaci bez provider I/O při čtení.
- Důkaz: [current_value/api.py:43](D:/Programing/finance-app/backend/python/app/modules/current_value/api.py:43), [current_value/service.py:1231](D:/Programing/finance-app/backend/python/app/modules/current_value/service.py:1231), [api/router.py:38](D:/Programing/finance-app/backend/python/app/api/router.py:38).

#### V04 — P2: Dávkové čtení a paměťová cache nejsou dotažené

- Cold read dělá sériové dotazy účet po účtu. Naměřeno 16 SQL příkazů pro portfolio se dvěma účty a 41 pro dashboard se šesti účty; cache-hit 5 příkazů.
- Cache-hit projekce byl kolem 12–14 ms; první portfolio read v novém procesu 383 ms včetně navázání DB spojení. Nejde o produkční p95 benchmark.
- Cache expiruje položku jen při čtení stejného klíče. Nové publikace vytvářejí nové klíče a staré expirované záznamy bez dalšího přístupu zůstávají v procesní paměti. Chybí globální omezení/evikce.
- Oprava: dávkové načtení zachovávající autorizaci a ohraničená privátní cache. Výkon doložit na 1, 5 a 20 účtech.
- Důkaz: [multi_account_service.py:265](D:/Programing/finance-app/backend/python/app/modules/portfolio_snapshot/multi_account_service.py:265), [published_snapshot/api.py:42](D:/Programing/finance-app/backend/python/app/modules/published_snapshot/api.py:42).

#### V05 — P2: Chyba importu ztrácí příčinu a zotavení může viset

- Po vyčerpání pokusů worker přepíše původní chybu na obecné `background_job_attempts_exhausted`. UI zobrazí pouze zprávu, nikoli fázi a počty pokusů. To vysvětluje opakovanou nicneříkající hlášku; nedokazuje příčinu konkrétního importu.
- Globální monitor mimo stránku Import zastaví polling neúspěšného jobu bez oznámení.
- Souborový `publish.lock` má nekonečné čekání. Pád procesu po vytvoření locku může blokovat další upload/retry daného batch bez timeoutu a bezpečného stale-lock zotavení.
- Oprava: uchovat bezpečnou poslední příčinu/fázi, zobrazit stav a řízený retry; u locku zavést vlastnictví, časový limit a crash recovery.
- Důkaz: [jobs/worker.py:255](D:/Programing/finance-app/backend/python/app/modules/jobs/worker.py:255), [import/page.tsx:398](D:/Programing/finance-app/src/app/import/page.tsx:398), [storage.py:52](D:/Programing/finance-app/backend/python/app/modules/imports/storage.py:52).

#### V06 — Riziko k potvrzení: Příliš stará intradenní evidence

- Plánovač v režimu `local_free` omezuje subdaily historii, ale do každého rozlišení znovu vloží boundary první události, i když je mimo provider lookback.
- Pokud v tomto bodě potřebuje skutečnou intradenní cenu/FX, worker může žádat nedostupná data. Konkrétní provider-backed reprodukce pro uživatelův účet nebyla provedena.
- Oprava: zachovat počátek historie ve skutečně dostupném rozlišení; nevymýšlet intradenní ceny z denního close.
- Důkaz: [builder/planning.py:139](D:/Programing/finance-app/backend/python/app/modules/portfolio_history/builder/planning.py:139), [builder/market.py:265](D:/Programing/finance-app/backend/python/app/modules/portfolio_history/builder/market.py:265).

### Good to have — neblokuje stabilizační verzi

- Souhrnná alokace napříč investičními účty a dokončený graf detailu instrumentu.
- Přehled fronty importů s globálním upozorněním na dokončení/selhání a vysvětlením, kdy už je bezpečné stránku opustit. Dnešní upload ukládá soubory postupně před vytvořením durable jobu; samotná práce po zařazení už asynchronní je.
- Bohatší detail transakcí, přílohy a případná data o záruce. CSV může převzít pouze údaje, které export obsahuje. Účtenka není běžnou součástí bankovního CSV a nelze ji spolehlivě rekonstruovat z popisu platby.
- Uživatelské diagnostické informace bez surových importů, tokenů a finančních částek v logu.
- WebSocket/SSE není opravou současných chyb; nejprve musí být správná publikace, čtení a běžný polling.

### Co je doloženě dobrý základ

- Python vlastní většinu autorizace a finančních pravidel; peněžní typy jsou převážně přesné `Decimal`.
- Importy mají durable fáze, idempotenci a opětovnou kontrolu klasifikace při zápisu. Nejasné řádky se ve zkoumaných cestách nezapisují potichu.
- Trading Card má explicitní provozní klasifikaci; nelze všechny problémy připsat aliasům aktiv.
- Ruční canonical změny mají historii invalidací, transakční hranice a deterministické identity pro retry.
- Snapshotové hlavní FE read cesty nevyžadují při otevření provider síťové volání. Chart komponenty jsou odděleně načítané; dashboard spouští finanční/provozní načtení souběžně.
- Přímá shoda SQLAlchemy se živým PostgreSQL schématem je ověřena; Alembic head je `400001anycoinvaluation`.

## 2. Co musí být hotové pro osobně použitelnou verzi

### Etapa A — Reprodukovatelný a bezpečný základ

1. Uchovat zálohu a vybrat jednoznačný pracovní stav; nezahazovat existující změny.
2. Sjednotit zamčené závislosti v CI, lokálu a Dockeru; odstranit nesoulad starých souborů v image. Zelená schema parity i celý migrační preflight.
3. Omezit přístup k API/DB, odstranit známý interní klíč, zavést nesuperuživatelskou DB roli a aktualizovat zasažené knihovny. Před sdílením opravovat S01 a relace po změně hesla; doplnit ochranu přihlášení.

Přijato teprve tehdy, když čistý image odpovídá zdrojům/lockfile, schéma projde kontrolou a lokální API/DB nejsou nechtěně vystavené.

### Etapa B — Znovu spolehlivě publikovat snapshoty a historii

4. Opravit F01 a F04 společným kontraktem včetně původních měn, přesnosti, coverage a všech rozsahů.
5. Opravit F02: aktuální obnova nesmí nahradit úplnou řadu jedním bodem.
6. Opravit F03/F05: životní cyklus generací, opuštěná práce, souběh capture/refresh a idempotentní finalizace. Následně řízeně obnovit blokované joby a snapshotové projekce, nikoli mazat canonical/import/price/FX evidenci.
7. Vyjasnit V06 a dostupnost historických cen/FX pro skutečně používané instrumenty. Chybějící evidence musí být konkrétní stav k řešení, ne nekonečný retry.

Přijato teprve tehdy, když rok/ALL i konkrétní účet vrací graf, následující refresh zachová staré body, pozdní import opraví správný úsek a restart/selhání workeru neblokuje další práci ani nezveřejní neúplnou sadu.

### Etapa C — Pravdivé a konzistentní zobrazení

8. Oddělit čas publikace od stáří cen/FX; test upozornění po 30 minutách. Přidat identitu použité publikace do všech souvisejících finančních odpovědí, kde nyní chybí.
9. Při výběru historického bodu přepnout všechny hodnoty na tentýž čas; chybějící historické pole označit jako nedostupné. Žádný fallback na dnešní peníze.
10. Opravit 204 transport, refresh provozního dashboardu, závody filtrů a stav chyby/načítání. Explicitně odlišit prázdná data, chybu, poslední platný stav a zastaralé ceny.
11. Zpřesnit importní hlášky, zachovat poslední příčinu/fázi a opravit lock/retry zotavení. Neplatné identifikátory musí jít do revize, ne do heuristické deduplikace.

Přijato teprve tehdy, když FE nerozporuje stav BE, přepnutí filtrů neukáže opožděnou odpověď, import dokončený na pozadí obnoví dotčené údaje a uživatel pozná proč operace selhala.

### Etapa D — Výkon bez změny finančních pravidel

12. Opravit naměřený SQL/JIT problém provozního dashboardu; zachovat autorizační a publikační filtry.
13. Dávkové snapshotové dotazy, ohraničená cache, proměřené časy autentizace/DB/projekce/serializace. Oddělit vývojovou kompilaci Next.js od provozních latencí.
14. Změřit 1, 5 a 20 účtů, dlouhou historii a souběh s importem. Teprve z dostatečného počtu požadavků vyhodnotit p50/p95/p99. Cíl pro publikované běžné čtení zůstává p95 ≤ 100 ms na produkčně podobném prostředí.

### Etapa E — Vydávací podmínky a determinismus

Determinismus znamená: stejné canonical události + stejná zmrazená cenová/FX evidence + stejné verze pravidel dají stejné finanční výsledky. Nová tržní cena smí vytvořit nový výsledek; rozdílné pořadí workerů nesmí samo změnit finanční význam.

Minimální end-to-end sada v oddělené databázi:

- Anycoin a Trading: běžný import, duplicita, pozdní řádek, nejasná položka k revizi, více souborů, více měn a Trading Card cash-flow.
- Import → canonical evidence → holding → všechny čtyři snapshoty → publikace → skutečný JSON → frontendové validátory → graf/UI.
- Opakování stejného jobu, dva workery, restart uprostřed práce, vyčerpané pokusy, provider timeout a zotavení opuštěné generace.
- Před/po publikaci viditelná vždy úplná koherentní sada; nový refresh neodstraňuje dostupnou historii.
- Odvolání sdílení, izolace cache a účtů, změna uživatele/odhlášení, stará relace po změně hesla.
- Součty snapshotů, původní měny, event-date FX, nákladová báze, čisté vklady, P/L a historické alokace oproti ručně ověřenému malému vzorku.
- Ověřená záloha a obnova. Zelené typy, lint, relevantní unit/integration/E2E testy a měření výkonu; žádné pouhé nahrazení starých kontrol zdrojového textu novými očekáváními.

Po těchto etapách dává smysl označit vydání za osobně použitelné. Rozšíření typu přílohy, záruky a WebSockety mohou počkat. Nelze poctivě slíbit absolutní absenci všech bugů; lze stanovit konkrétní invarianty, reprodukovatelné scénáře a podmínky, bez kterých verze nebude vydána.

Mazání celé DB není řešení nalezených chyb: chyby publikace, scheduleru a FE/BE kontraktu by vznikly znovu. Tento audit žádná data nesmazal ani žádnou z oprav neimplementoval.
