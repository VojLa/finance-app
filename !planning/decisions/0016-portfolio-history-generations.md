# ADR 0016 - Versioned portfolio history generations

Status: Superseded
Date: 2026-08-20
Decision owners: finance-app owner
Supersedes: none
Superseded by: ADR 0022 - Unified renewable snapshot projections

Implementation status (2026-08-25): schema `3q`/`3r`, historical providers,
Prague lattice, replay, immutable publication, compaction/audit/cleanup and the
generation-backed API/UI reader are implemented in the working tree. Live database
migration, runtime rollout, remaining write-boundary invalidations and final
disposable/browser acceptance remain rollout gates.

## Kontext

Soucasna historie portfolia pouze cte fyzicke `NetWorthSnapshot` radky. Import
publikuje jeden aktualni minutovy `import_event` snapshot, ale nevytvari
historicke oceneni od prvni canonical udalosti. Pozdni import proto nemuze
opravit drive vytvorene body a uzivatel, ktery nahraje nekolik let stare
transakce, neuvidi pravdivy historicky vyvoj.

Existujici `AccountSnapshot` a `NetWorthSnapshot` maji nemennou identitu bez
generace. Opravena hodnota ve stejnem timestampu by byla konfliktem, nikoliv
bezpecnym rebuildem. `DailySnapshotBaseline` a R12 minutove importni anchory
navic vlastni current-value publication boundary a nesmi se stat pracovnim
prostorem historickeho backfillu nebo compaction.

Historie musi soucasne podporovat pozdni canonical data, periodicke snimani,
omezene mnozstvi bodu v grafu, dlouhodobou retenci, crash-safe retry a sdilene
ucty bez zobrazeni castecne prepsane casove rady.

## Rozhodnuti

### Oddelena verzovana projekce

Historicky graf bude samostatny rebuildovatelny read model. Nova
`PortfolioHistoryGeneration` zmrazi uzivatele, menu, aktualni account/member
scope, canonical revisions, calculation version, source-policy version a
retention-policy version. Ulozi take SHA-256 kompletniho frozen canonical
vstupu vcetne presneho listing provideru a provider symbolu. Body se nejprve
vytvori v neverejne generaci a publication tento vstup znovu zmrazi a porovna.

Jeden `PortfolioHistoryPublication` ukazuje na jedinou verejnou generaci.
Prepnuti pointeru, oznaceni predchozi generace jako superseded a uzavreni
zpracovane invalidace probehne v jedne databazove transakci. Reader proto vidi
bud celou starou, nebo celou novou generaci.

Historicke tabulky jsou oddelene od `AccountSnapshot`, `NetWorthSnapshot`,
`DailySnapshotBaseline` a `ImportJobPublicationTarget`. Soucasne snapshoty,
R12 publication fence a baseline-plus-delta current-value engine se timto
rozhodnutim nemeni.

### Povinna invalidace a backfill

Kazda nova canonical `Transaction`, `InvestmentEvent` nebo `LiabilityBalance`
zneplatni historii vsech aktualnich clenu dotceneho uctu od sveho
`financialTimestamp`. `PortfolioHistoryDirtyState.dirtyFrom` je vzdy minimum
vsech nezpracovanych dopadu. Duplicitni import bez nove canonical udalosti
existujici kompletní historii nezneplatni; pokud generace jeste neexistuje,
zalozi prvni rebuild.

Importni completion transakce musi pred dokoncenim R12 jobu pro kazdeho
aktualniho clena atomicky ulozit dirty range a durable history job. Samotny
dlouhy backfill neblokuje current publication. Import `completed` tedy znamena,
ze je atomicky publikovane aktualni portfolio a ze historicka oprava byla
durable prijata, nikoliv ze uz je prepocet historie hotovy. API a UI musi tyto
dva stavy rozlisovat.

Rebuild zacina prvni canonical financni udalosti. Pouzije jeden chronologicky
replay, ktery drzi prubezny cash, liability, quantity a cost-basis stav; nesmi
pro kazdy bod znovu prehravat celou historii. Kompatibilni prefix drivejsi
generace pred `dirtyFrom` lze presne zkopirovat. Pokud se behem buildu zmeni
dirty revision, membership, base currency nebo canonical manifest, rozpracovana
generace se nezverejni a job zpracuje nove sjednocene rozmezi.

Generace ma databazove omezeny `buildCause`: `rebuild` nese presny nenulovy
`buildDirtyEpoch` a `buildFrom` z uzamceneho dirty stavu; `capture` ma epoch
NULL a presny Prague bucket close; `compaction` ma epoch NULL a presny parent
publication id+version i input generation/hash. Capture ani compaction dirty
stav nemazou. Pouze initial rebuild smi mit parent fence kompletne NULL.

### Samostatne history joby

Historie pouzije vlastni PostgreSQL-backed `PortfolioHistoryJob` lifecycle pro
`rebuild`, `capture`, `compact` a `audit`. Claim, lease, heartbeat, retry a
bezpecne chyby zachovaji principy ADR 0011, ale nebudou zobecnovat ani menit
R12 `BackgroundJob`. Soucasny worker, payload, progress, completion a schema
constrainty jsou import-specific; jejich zmena by zbytecne ohrozila overenou
R12 publication fence.

Pro jednoho uzivatele muze bezet nejvyse jeden history job. Joby jsou
idempotentni a pouzivaji `FOR UPDATE SKIP LOCKED` a fenced lease. Provider nebo
replay failure ponecha posledni publikovanou generaci beze zmeny.

### Historicke market evidence

Backfill nesmi opakovane volat current-quote adapter pro kazdy bucket. Provider
hranice dostanou explicitni historicke range/batch porty pro Yahoo Finance,
CoinGecko a Twelve Data price a FX data. Pozadavek se seskupi podle presneho
persistovaneho listing/pair/provider identity a casoveho rozsahu.

Kazdy bod smi pouzit pouze posledni schvalenou evidence s casem mensim nebo
rovnym casu bodu. Budouci cena, neoznaceny provider fallback, pivot nebo inverse
FX zustava zakazany. Chybejici historicka evidence vytvori bezpecne selhani
generace; hodnota se nevymysli. Pouzite `PriceSnapshot` a `ExchangeRate`
identity budou normalizovanou lineage historickeho account pointu.

Interval historickeho provider requestu popisuje granularitu fyzicke evidence,
nikoli rozliseni portfolio bodu. Canonical Twelve Data history adapter pouziva
pro listed price i primy FX pouze skutecne dokoncene 30minutove bary v UTC.
Twelve Data daily bar neni pro listed cenu prijat, protoze jeho lokalni datum
bez persisted exchange timezone a close kalendare neurcuje jednoznacny UTC
as-of okamzik. I denni nebo hrubsi portfolio bod proto smi vybrat posledni
skutecny 30minutovy close `<= representativeAt`; bar se nepreznaci jako daily,
neopakuje do intraday bodu a nevytvari inverse, pivot ani provider fallback.
Request window se z close-time kontraktu prelozi na bar-open hranice, takze
`end_date` nezada prave otevreny bar, ktery by skoncil az po valuation case.
Provider requesty se deli nejvyse po 100 dnech, aby jeden 30minutovy vysledek
zustal pod limitem 5 000 hodnot. Produkcni rollout musi pred zapnutim workeru
overit, ze konkretni Twelve Data tarif dovoluje potrebnou hloubku intraday
historie pro intended backfill; chybejici entitlement nebo coverage skonci
fail-closed a stara kompletni generace zustane publikovana.

`local_free` subdaily kontrakt je vyhradne vyvojovy a fail-closed. Yahoo
Developer API katalog nepublikuje Finance Chart API; pouzity anonymni chart
endpoint proto neni produkcni SLA ani canonical provider. Credential-free live
probe 2026-08-20 pro `VUAA.MI` a primy par `EURCZK=X` vratil pro `interval=30m`
`dataGranularity=30m` na 1, 8, 30 a 59 dnech a HTTP 422 na 60, 61 a 90 dnech.
Adapter proto kontroluje symbol, menu, `dataGranularity`, dokoncenou 30minutovou
bar periodu, velikost odpovedi a empiricky 59denni limit, pozadavky deli nejvyse
po sedmi dnech a nikdy nepouzije inverse nebo pivot FX. Starsi Yahoo vrstva
zustava denni pouze pro explicitne denni bucket; `provider_determined` mimo
bezpecny recentni rozsah failne a nesmi potichu prejit na daily. S povinnym
lookbackem je bezpecna subdaily historie asi 55 dni pro listed price a 51 dni
pro FX; capability plan pouzije spolecny konzervativni limit 50 dni. H4 zustava
idealnim maximem, ale H7 pro `local_free` ořízne 6h/12h detail na 50 dni a starsi
cast pokryje vrstvou `>=1d`. Canonical Twelve Data muze drzet 90 dni. Reader
smí pro `3M` slozit starsi daily a recentni 12h body jen kdyz u kazdeho bodu
zachova skutecne resolution/coverage; nesmi tvrdit jednotnych 12h pro cely
rozsah. Zdroj: [Yahoo Developer API katalog](https://developer.yahoo.com/api/).

CoinGecko `/coins/{id}/market_chart/range` dokumentuje automatickou granularitu:
posledni den od aktualniho casu vraci petiminutova data, jiny jednodenní rozsah
a 2--90 dni hodinova data a nad 90 dni denni data. `provider_determined` proto
neznamena 30 minut: rolling 1D overi souvislou zhruba petiminutovou radu,
2h/32denni vrstva overi hodinovou radu a starsi explicitne denni buckety
zustanou denni; subdaily pozadavek nad limitem failne. Live
credential-free probe 2026-08-20 pro `bitcoin`/`CZK` potvrdil 287 petiminutovych
bodu pro 23 h 55 min, hodinovou granularitu pro historicky 1 den i aktualnich
8 dni a HTTP 429 pri vycerpani sdilene kvoty. Raw timestampy se zachovaji;
denni close se nesmi vydavat za subdaily. Keyless API ma dynamicky limit asi
10--30 volani/min, neni urceno pro production polling a pri 429 adapter selze
bez fallbacku. Zdroje: [CoinGecko range granularity](https://docs.coingecko.com/reference/coins-id-market-chart-range),
[CoinGecko keyless API a limity](https://docs.coingecko.com/docs/keyless-public-api).

Implementacni credential policy zachovava tri explicitni rezimy bez fallbacku.
Bez klice pouzije historical adapter public base, se samotnym Demo klicem stejny
base a header `x-cg-demo-api-key`, a se samotnym Pro klicem pevny base
`https://pro-api.coingecko.com/api/v3/coins` a header `x-cg-pro-api-key`.
`COINGECKO_DEMO_API_KEY` a `COINGECKO_PRO_API_KEY` jsou vzajemne vylucne a
ambiguitni konfigurace failne pri startu. Pro klic je urcen pro server-side
long-range backfill s odpovidajicim Analyst-or-higher entitlementem; neni v URL,
query, logu ani browser konfiguraci a chyba entitlementu nebo kvoty neprepina
provider ani credential rezim.

### Praha, rozliseni a retence

Fyzicke timestampy zustavaji naive UTC `TIMESTAMP(3)`. Calendar a wall-clock
hranice pouzivaji IANA zonu `Europe/Prague`, nikoliv pevne CET. Intraday buckety
se kotvi k lokalni pulnoci a vice-denni buckety k deterministickemu lokalnimu
date ordinal. Prechod letniho casu proto muze mit 46 nebo 50 pulhodinovych
slotu.

Vrstvy jsou vnorene:

```text
30 min -> 2 h -> 6 h -> 12 h -> 1 den -> 2 dny -> 4 dny ->
8 dni -> 16 dni -> 32 dni
```

Verejne range pouziji:

| Range | Rozliseni                                       |
| ----- | ----------------------------------------------- |
| `1D`  | 30 minut                                        |
| `1W`  | 2 hodiny                                        |
| `1M`  | 6 hodin                                         |
| `3M`  | 12 hodin                                        |
| `6M`  | 1 den                                           |
| `1Y`  | 1 den                                           |
| `5Y`  | 4 dny                                           |
| `10Y` | 8 dni                                           |
| `ALL` | nejjemnejsi z 8/16/32... dni s nejvyse 480 body |

Verejny reader pouzije tabulku jako preferovane rozliseni, ale nesmi predstirat
coverage, ktera v teto vrstve neni. Mezery v preferovane vrstve vyplni pouze
nejblizsi hrubsi vrstvou s ulozenou `complete` coverage; nikdy nepouzije jemnejsi
vrstvu, interpolaci, inverse/pivot FX ani opakovany daily close. Vysledkem proto
muze byt jedna mixed-resolution rada, ve ktere kazdy bod nese sve skutecne
`resolutionMinutes` a serverem vybrane coverage segmenty. Server zachova poradi,
jedinecnost timestampu, exact first-event boundary a limit nejvyse 480 bodu.
Browser body pouze zobrazi a sam je neslucuje ani neprepocitava.

Retence nejjemnejsich dostupnych dat je 30 minut po 24 hodin, 2 hodiny po 32
dni, 6 a 12 hodin po 90 dni, 1 den po 400 dni, 2 dny po 800
dni, 4 dny po 6 let a 8 dni po 12 let. Vrstvy 16/32 dni jsou dlouhodobe.
Denní close se nesmí opakovat jako falešná intradenní evidence.

Prvni canonical udalost ma retention-exempt boundary point. Compaction nikdy
nepouzije aritmeticky prumer net worth. Parent uklada prvni `open`, skutecne
`high/low`, posledni `close`, pocet vzorku a source manifest. Graf pouziva
`close`.

### Scheduler, capture a compaction

Scheduler pod kratkym PostgreSQL advisory lockem vytvari splatne 30minutove
capture joby. Pokud historie chybi, capture vyvola rebuild od prvni udalosti.
Pokud je uzivatel dirty nebo building, capture se odlozi. Po delsim vypadku se
chybejici interval doplni z historical provider evidence; nevytvori se pouze
jeden aktualni bod.

Compaction nejprve vytvori a overi parent rollupy a teprve potom v samostatne
bezpecne fazi odstrani expired detailni history points. Nikdy nemaze canonical
udalosti, market evidence, soucasne snapshoty, R12 import anchors, aktualni
generaci bez overene nahrady ani predchozi rollback generaci v ochranne lhute.

Cleanup nemaze hlavicku superseded generace. Sedmidenni rollback okno se pocita
od atomicky nastaveneho `supersededAt`, nikoli od puvodniho `finishedAt`;
legacy superseded radek s NULL `supersededAt` se automaticky necisti. Po okne
smi cleanup v jedine transakci odstranit pouze generation-owned child payload a
ulozit nemenny cleanup receipt s presnym manifest hashem a pocty odstraneneho
payloadu. Hlavicka generace, parent/input ID a hashe zustavaji jako provenance
tombstone. Cleanup je povolen jen pro superseded generaci, ktera neni aktualni
publication, ma uspesny audit odpovidajici aktualni publication a projde
nezavislou kontrolou integrity pod zamkem. Jediny failed kandidat je presne
oploceny compaction orphan po stale-publication race a stejnem sedmidennim okne.
Z vice kandidatu se pod zamkem vybere deterministicky nejstarsi a jeden job
odstrani nejvyse jeden payload. Chybejici nebo zastaraly audit, korupce nebo
publication race znamena nulove mazani.
Canonical data, market evidence, R12/D1 evidence a vsechny current nebo
rollback-protected generation payloady cleanup nikdy nemeni.

### Sdilene ucty

Import dotceneho uctu invaliduje user-level historii kazdeho jeho aktualniho
clena, vcetne vieweru. Kazda user generation obsahuje vsechny aktualne
pristupne aktivni ucty daneho uzivatele.

Soucasne schema nema intervalovou historii clenstvi. Pro MVP se proto aktualni
membership promita na celou generovanou historii. Pridani nebo odebrani clena,
archivace uctu nebo zmena account scope invaliduje generaci od nejstarsi
udalosti dotceneho scope. Skutecne membership-as-of chovani vyzaduje nove
canonical membership intervaly a neni timto rozhodnutim predstirano.

Scope mutation a invalidace jsou jedna transakce pod serazenymi user-level
generation advisory locky. Pocitaji jen accepted membership. Odebrani clena,
archivace a skutecna zmena meny nejprve zmrazi stary dotceny scope; create,
accept a restore nejprve zapisi novy scope. Po zamku se account i membership
znovu zamknou a presne overi. Scope invalidace pouziva explicitni runtime
source policy, nevytvari canonical receipt a dirty hranici sklada jako minimum
aktualni replay-visible udalosti, existujiciho dirtyFrom a publikacniho
replayFrom. Same-value a ciste prezentacni zmeny zadnou invalidaci nevytvareji.

Pokud scope-dirty rebuild pod generation lockem znovu overi, ze uzivatel nema
zadny aktualni accepted a aktivni ucet, nevytvari prazdnou generaci. V jedine
SERIALIZABLE transakci se presny publikovany pointer odstrani, jeho verified
generace se oznaci `superseded` a dostane pouze `supersededAt`; puvodni
`finishedAt` se zachova jako provenance dokonceni buildu. Dirty a schedule stav
se odstrani, ostatni queued/running/retry-wait history joby dostanou permanentni
`history_scope_retired` a novy lease version fence a ostatni nepublikovane
building/verified generace selzou pod stejnym kodem. Aktualni rebuild zustane
oploceny svym leasovacim vlastnikem, atomicky ulozi checkpoint receipt s presnym
generation ID a publication version a dokonci jako `no_work`; crash mezi
retirementem a completion proto opakuje stejny receipt bez druheho prechodu.
Payload a hlavicka superseded generace zustavaji zachovane. Dokud neexistuje nova
publication a odpovidajici uspesny audit, cleanup tento retirement payload nesmi
odstranit. Reader pocita `hasEvents` jen z aktualnich accepted a aktivnich uctu,
takze archivovane membership koreny nesmi predstirat neprazdnou historii.

Pozdeji prijaty clen proto smi replayovat i starsi importovane koreny uctu.
Aktualni accepted membership autorizuje cely aktivni ucet; samotny importovany
koren je vsak zahrnut jen tehdy, kdyz jeho presny batch skoncil completed nebo
partially completed, jeho presny durable import job skoncil completed a tento
job ma publikovany `ImportJobPublicationTarget` puvodniho importujiciho
uzivatele. Target ciziho uzivatele, jineho jobu nebo uctu, nepublikovany target
a queued/failed job nebo batch zustavaji fail-closed. Toto nemeni R12 targety
ani nepredstira historicke intervaly clenstvi.

## Dusledky

- Pozdni petidenni i petilety import opravi odpovidajici historicky suffix.
- Verejna rada zustane behem dlouheho rebuildu koherentni a dostupna ve stare
  generaci.
- Stara cast backfillu se vytvari rovnou v retenčním rozliseni; nevznika
  zbytecna pulhodinova petileta rada.
- Historicky replay, range providery, scheduler a compactor jsou nove slozite
  boundaries vyzadujici PostgreSQL, crash/retry, DST a provider testy.
- Fyzicke history pointy mohou byt rebuildovany a odstranovany bez poruseni
  canonical nebo R12 current-value auditu.
- Dokud nejsou podporovany presne as-of bank/cash/savings snapshoty, nelze
  tvrdit uplny RB/net-worth history PASS.

## Zamitnute alternativy

- Prepis existujicich `NetWorthSnapshot` radku: porusuje immutable identity a
  R12/D1 lineage.
- Jedna dlouha transakce od importu po petilety backfill: blokuje current
  portfolio a nema bezpecny recovery lifecycle.
- Jeden obecny refactor R12 `BackgroundJob`: zvysuje regresni riziko hotove
  importni publication fence.
- Prepocet cele historie pro kazdy bod: neprimerena casova slozitost.
- Prumerovani net worth pri downsamplingu: zkresluje vklady, vybery a skokove
  udalosti.
- Pevne CET nebo UTC-denni buckety: nesplnuji lokalni kalendar a DST.
- Pouziti aktualnich Holdings pro historicky bod: zahrnuje budoucí udalosti a
  je financne nespravne.

## Migracni nebo rollout plan

1. Zaznamenat detailni implementacni krok a uzavrit cash-account/as-of
   semantics bez zmeny R12.
2. Pridat Alembic schema a SQLAlchemy parity pro history jobs, dirty ranges,
   schedules, generations, publication, account points a market lineage.
3. Implementovat Prague bucket/retention engine a pure chronological replay.
4. Implementovat historical range/batch providery.
5. Implementovat generation builder, validaci a atomickou publication.
6. Zapojit invalidaci do vsech canonical write boundaries a R12 completion
   transakce.
7. Pridat scheduler, capture, compaction a audit.
8. Dokonceno v kodu: prepnout history API/UI na generation pointer, vsech devet
   rozsahu `1D` az `ALL`, mixed preferred-to-coarser complete coverage a skutecne
   rozliseni kazdeho bodu.
9. Provest PostgreSQL, browser, crash/retry, DST, late-import a load acceptance.

Kodovy reader cutover je hotovy a puvodni `NetWorthSnapshot` history reader byl
odstranen; live rollout zustava zablokovany do zeleneho disposable PostgreSQL gate.
Migrace sama nesmi existujici snapshoty prohlasit za kompletni historickou generaci
bez dokazatelne lineage.
