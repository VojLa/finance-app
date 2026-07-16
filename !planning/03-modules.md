# Modules

## Smysl dokumentu

Tento dokument urcuje hlavni moduly aplikace, jejich odpovednost, vlastnictvi dat a jasne hranice mezi nimi. Cilem neni jen vyjmenovat domeny, ale rozhodnout:

- kam patri nova logika,
- ktery modul je source of truth pro ktera data,
- co smi ktery modul zapisovat,
- co si ma modul jen cist jako zavislost,
- co do modulu naopak nepatri.

Pokud bude pri implementaci nejasne, kam novou vec zaradit, ma se rozhodovat podle tohoto dokumentu a ne podle toho, kde je zrovna v kodu misto.

---

## Domenova filozofie

Business logika je rozdelena podle domen.

Kazda domena:

- vlastni sva data,
- poskytuje verejne rozhrani,
- nesmi obchazet ostatni moduly primymi zapisy do jejich dat.

Komunikace mezi moduly probiha pouze pres definovane kontrakty. Pokud dva moduly potrebuji spolupracovat, nesmi se spojit nahodnym primym zasahem do interniho stavu toho druheho modulu.

Source of truth se deli podle vrstvy:

- `Python API` je source of truth pro backendovou business logiku a use-cases,
- `Prisma schema` je aktualni source of truth pro fyzicky DB model,
- databazove tabulky jednotlivych domen jsou source of truth pro konkretni ulozena data,
- read modely a snapshoty jsou odvozene vrstvy, ne primarni pravda o historii.

To znamena, ze prechod backendu do Pythonu neni v rozporu s tim, ze schema databaze je zatim rizena pres `Prisma`. Kazda vec jen vlastni jinou vrstvu systemu.

---

## Zakladni principy

- `Next.js` frontend nevlastni domenovou logiku. Patri do nej UI, routing, formulare a klientsky stav.
- `Python API` je hlavni backendova vrstva a misto, kde zije obchodni logika.
- `PostgreSQL` je centralni persistence vrstva.
- `Prisma schema` je source of truth pro fyzicky DB model, ne pro business logiku.
- `Rust` patri jen do vypocetne tezkych deterministickych enginu, ne do orchestrace nebo API.
- Kazdy modul ma mit jasnou odpovednost a nemel by zapisovat data, ktera patri jinymu modulu.
- Read modely nejsou source of truth. Jsou odvozene z primarnich dat a slouzi pro rychle cteni.

---

## ASCII diagram

```text
Frontend
    |
    v
Python API
    |
    +-------------------+-------------------+-------------------+-------------------+
    |                   |                   |                   |                   |
    v                   v                   v                   v                   v
Auth               Accounts             Imports              Assets           Notifications
                        |                   |                   |
                        |                   v                   v
                        |                Parsers           Prices and FX
                        |                   |                   |
                        |                   +---------+---------+
                        |                             |
                        v                             v
                                     Ledger -------> Holdings
                                        |               |
                                        v               |
                                    Snapshots <---------+
                                        |
                                        v
                                   Read Models
                                   |    |    |    |
                                   v    v    v    v
                              Portfolio Dashboard Reports Analytics

Cross-cutting:
- Audit
- Jobs and Background Processing
- Shared (no business logic)
```

---

## Hlavni vrstvy systemu

### 1. Frontend

Patri sem:

- stranky,
- komponenty,
- formulare,
- grafy,
- klientsky fetch a cache stav,
- loading, error a success UX.

Nepatri sem:

- vypocet portfolio hodnot,
- parser logika,
- ledger replay,
- snapshot vypocty,
- FX prepocet,
- rozhodovani o tom, co se uklada do DB.

Frontend muze:

- volat oficialni backend kontrakty,
- skladat data pro zobrazeni,
- drzet docasny UI stav.

Frontend nesmi:

- byt source of truth pro financni vypocty,
- duplikovat backend business rules.

### 2. Python API

Patri sem:

- HTTP endpointy,
- aplikacni orchestrace,
- validace vstupu a vystupu,
- import workflow,
- backend use-cases,
- job orchestrace,
- modulove service boundary.

Nepatri sem:

- React nebo Next-specific typy,
- detailni vykreslovaci logika UI,
- nahodne cross-module utility bez vlastnika.

### 3. Rust engine

Patri sem:

- deterministicke vypocetni jadro,
- ledger replay,
- snapshot build,
- vykonove narocne portfolio a FX vypocty.

Nepatri sem:

- DB pristup bez explicitniho rozhodnuti,
- endpoint orchestrace,
- auth,
- parser-specific UI a dokumentace.

Datova hranice mezi `Python` a `Rust` musi byt explicitni:

- vychozi pravidlo je, ze `Python API` nacte domenova data a preda `Rustu` ciste datove struktury pro vypocet,
- `Rust` nema automaticky primy pristup do `PostgreSQL`,
- read-only pristup `Rustu` do konkretnich tabulek je mozny jen pri vedomem architektonickem rozhodnuti pro vykonove narocne use-cases,
- i v takovem pripade zustava orchestrace, job lifecycle a business boundary v `Python API`.

### 4. Database

Patri sem:

- primarni data,
- historicka data,
- referencni market data,
- materializovane snapshoty a read-side cache, pokud je chceme trvale ukladat.

DB nesmi byt:

- mistem, kde se skryva nezdokumentovana business logika,
- nahodnym odkladistem pomocnych poli bez vlastnika.

---

## Modulovy model

### Accounts

Ucel:
Spravuje financni ucty jako vlastni kontejnery dat a hlavni menu uctu.

Source of truth:

- ucet,
- typ uctu,
- hlavni mena uctu,
- stav archivace,
- vztah uctu k uzivateli.

Patri sem:

- vytvoreni a sprava uctu,
- metadata uctu,
- account ownership boundary,
- account-level nastaveni.

Nepatri sem:

- importni radky,
- parser logika,
- portfolio vypocty,
- snapshot build,
- market data.

Tento modul smi zapisovat:

- account entity a jeji metadata.

Tento modul smi cist:

- read modely pro account overview,
- import batch stav pro ucet.

Tento modul nesmi:

- sam pocitat holdings nebo snapshoty,
- drzet druhou kopii portfolio totals jako vlastni source of truth.

---

### Assets

Ucel:
Spravuje identitu aktiv a jejich canonical reprezentaci napric celym systemem.

Source of truth:

- asset,
- asset type,
- asset identity,
- listing identity,
- aliasy,
- vazby mezi canonical assetem a provider-specific symboly nebo exchange podobami.

Patri sem:

- globalni asset katalog,
- `Asset`,
- `AssetListing`,
- `AssetAlias`,
- pravidla identity pro jeden asset s vice listingy, symboly a provider mappingy.

Nepatri sem:

- price history jako takova,
- portfolio valuace,
- user-specific holdings,
- parser batch audit.

Tento modul smi zapisovat:

- asset identity data,
- listing metadata,
- alias metadata.

Tento modul smi cist:

- parser identity vstupy,
- ledger references,
- price provider metadata.

Tento modul nesmi:

- sam urcovat portfolio hodnotu,
- drzet user-specific business stav.

---

### Imports

Ucel:
Ridi prijem souboru, import batch lifecycle, validaci, parse issues a prechod z externiho formatu do interniho normalizovaneho modelu.

Source of truth:

- import batch,
- import row audit,
- parse issues,
- import metadata,
- vazba mezi souborem a vytvorenymi udalostmi.

Patri sem:

- upload a prijem souboru,
- deduplikace importu,
- idempotence import workflow,
- multi-file batch orchestrace,
- unsupported row evidence,
- custom CSV fallback format,
- navody a kontrakt pro parser vstupy.

Nepatri sem:

- holdings vypocet,
- snapshot storage rozhodnuti,
- portfolio read model,
- market valuation.

Tento modul smi zapisovat:

- import batch a row audit data,
- normalizovane importni vysledky predane ledger modulu,
- status jobu importu.

Tento modul smi cist:

- account metadata,
- parser definitions,
- job status,
- asset/listing lookup pro normalizaci.

Tento modul nesmi:

- sam rozhodovat o finalni portfolio hodnote,
- sam udrzovat vlastni kopii holdings.

Dulezite pravidlo:
Pokud uzivatel nebo job nahraje stejny soubor opakovane, `Imports` musi zarucit, ze v `Ledgeru` nevzniknou duplicitni canonical udalosti.

---

### Parsers

Ucel:
Prekladaji konkretni externi exporty do jednotneho interniho importniho kontraktu.

Source of truth:

- parser-specific transform pravidla,
- mapovani externich sloupcu a typu radku,
- parser fixture testy.

Patri sem:

- logika pro jednotlive instituce,
- single-row a grouped parsery,
- custom CSV parser,
- parse issue generovani.

Nepatri sem:

- DB write orchestrace,
- holdings,
- snapshots,
- live ceny,
- dashboard logika.

Parsery smi vracet:

- normalizovane row vysledky,
- parse issues,
- dostatek raw kontextu pro audit a debugging.

Parsery nesmi:

- sahat primo do DB,
- obchazet import batch audit,
- pocitat read model totals.

---

### Ledger

Ucel:
Je source of truth pro investicni a portfolio udalosti. Definuje, co se skutecne stalo a jak se to rozpadne na pohyby aktiv, cash a dalsich hodnot.

Source of truth:

- investment events,
- investment movements,
- event typing,
- corporate action projection do canonical udalosti, pokud je potvrzena,
- external references importu,
- canonical investicni historie.

Patri sem:

- nakupy,
- prodeje,
- dividendy,
- fee,
- dane,
- vklady a vybery relevantni pro portfolio,
- prevody mezi ucty, walletami nebo platformami,
- currency conversion jako udalost nebo sada movementu,
- kompenzacni udalosti pro opravy historickych chyb,
- canonical dopad corporate actions na portfolio historii.

Nepatri sem:

- ulozene agregovane holdings jako primarni historie,
- snapshot bucketizace,
- UI summary logika.

Tento modul smi zapisovat:

- canonical eventy a movementy.

Tento modul smi cist:

- import normalized rows,
- account metadata,
- asset/listing identitu.

Tento modul nesmi:

- delat presentation-specific rozhodnuti,
- schovavat vypocetni zkratky jen kvuli dashboardu.

Dulezite pravidlo:
`Ledger` je append-only. Opravy se nedelaji tichym `UPDATE` historickych canonical udalosti. Pokud je potreba chybu opravit, ma se pouzit kompenzacni udalost, storno nebo nova opravna udalost tak, aby zustala zachovana auditovatelna historie.

---

### Holdings

Ucel:
Drzi aktualni agregovany stav pozic a cash, odvozeny z ledgeru. Je to aktualni stav, ne primarni historie.

Source of truth:

- aktualni pozice,
- aktualni mnozstvi,
- aktualni cost basis stav podle zvolene metodiky,
- aktualni cash breakdown podle men.

Patri sem:

- recalculation aktualniho stavu,
- account-level pozice,
- aktivni cash stav po menach,
- aktualni cost basis agregace pro zvolenou metodiku.

Nepatri sem:

- historicka pravda o tom, co se stalo,
- parser pravidla,
- live cena assetu,
- dlouhodoba portfolio historie.

Tento modul smi zapisovat:

- odvozene aktualni holdings a cash agregace.

Tento modul smi cist:

- ledger eventy a movementy,
- account metadata,
- asset/listing metadata.

Tento modul nesmi:

- byt jediny zdroj historie,
- prepisovat canonical ledger data.

Poznamka k danim:
`Holdings` muze drzet aktualni cost basis stav potrebny pro portfolio a beznou valuaci. Pokud budouci scope bude vyzadovat plnohodnotne danove reporty jako `FIFO`, `LIFO` nebo jurisdikcne specificke vypocty, ma vzniknout samostatny `Tax Engine`, ne dalsi lepeni danove logiky do `Holdings`.

---

### Corporate Actions

Ucel:
Spravuje trzni udalosti typu stock split, reverse split, merger, spin-off a dalsi neobvykle zmeny, ktere meni ekonomickou realitu drzenych aktiv, ale casto neprichazeji primo z bezneho uzivatelskeho importu.

Source of truth:

- corporate action definitions,
- vazba corporate action na asset nebo listing,
- pravidla, jak se trzni udalost promita do canonical portfolio udalosti.

Patri sem:

- evidovani corporate actions,
- validace a mapovani corporate action na konkretni asset/listing,
- preklad corporate action do udalosti, ktere `Ledger` umi zpracovat.

Nepatri sem:

- samotna aktualni portfolio valuace,
- parser batch audit,
- dashboard presentation.

Tento modul smi zapisovat:

- corporate action metadata,
- instrukce nebo canonical podklady predane `Ledgeru`.

Tento modul smi cist:

- `Assets`,
- `Prices and FX`,
- holdings nebo ledger references potrebne pro aplikaci corporate action.

Tento modul nesmi:

- potichu menit holdings bez canonical udalosti,
- obchazet `Ledger`.

Dulezite pravidlo:
Corporate action neni jen cenova informace. Pokud meni mnozstvi, cost basis nebo ekonomickou strukturu pozice, musi se nakonec projevit jako canonical zmena v `Ledgeru`.

---

### Prices and FX

Ucel:
Spravuje referencni market data a menove kurzy.

Source of truth:

- price snapshots,
- exchange rates,
- provider-specific cenova a kurzova data.

Patri sem:

- live a historicke ceny,
- FX kurzy,
- provider fallback pravidla,
- cenove a kurzove backfill workflow.

Nepatri sem:

- asset identity,
- portfolio read model totals,
- import batch audit,
- user-specific account metadata.

Tento modul smi zapisovat:

- market data a FX data,
- provider metadata relevantni pro ceny a kurzy.

Tento modul smi cist:

- asset/listing references z `Assets`, ledgeru a holdings,
- account main currency kvuli valuaci.

Tento modul nesmi:

- sam rozhodovat o tom, jaky snapshot se ma vytvorit,
- ukladat user-specific business stav mimo trzni data.

---

### Snapshots

Ucel:
Uklada point-in-time historicky stav uctu nebo portfolia, aby bylo mozne rychle cist historii bez plneho replaye vseho pri kazdem dotazu.

Source of truth:

- account snapshots,
- account snapshot items,
- net worth snapshots,
- snapshot metadata jako timestamp, granularity a source.

Patri sem:

- denni account snapshots,
- current-day live continuation z posledniho snapshotu,
- snapshot rebuild workflow,
- snapshot validation,
- historicke bucketizace a casove rady.

Nepatri sem:

- primarni definice toho, co se stalo v historii,
- parser logika,
- market provider rozhodnuti,
- UI-only grafove formatovani.

Tento modul smi zapisovat:

- snapshot tabulky a snapshot audit/logy.

Tento modul smi cist:

- ledger,
- holdings seed, pokud je rozhodnuto jako optimalizace,
- prices a FX,
- account metadata.

Tento modul nesmi:

- byt jedina evidence udalosti,
- menit canonical ledger historii.

Dulezite pravidlo:
Snapshot je odvozena vrstva. Pokud je konflikt mezi snapshotem a ledgerem, pravdu ma ledger a snapshot se rebuildi.

---

### Reconciliation

Ucel:
Detekuje a resi drift mezi interni odvozenou pravdou aplikace a externi realitou, kterou uzivatel vidi u brokera, banky nebo smenarny.

Source of truth:

- reconciliation runs,
- detected drift,
- reconciliation findings,
- stav vyreseni rozdilu.

Patri sem:

- porovnani internich holdings a cash s externim statementem,
- detekce chybejicich udalosti nebo nekonzistence importu,
- workflow pro oznaceni, ze data sedi nebo se rozchazeji.

Nepatri sem:

- canonical ledger storage,
- parser transform logika,
- portfolio presentation.

Tento modul smi cist:

- accounts,
- imports,
- ledger,
- holdings,
- snapshots,
- pripadne externi referencni statement data.

Tento modul nesmi:

- sam potichu opravovat canonical historii bez explicitniho opravneho workflow,
- prepisovat drift "jen aby to sedelo".

Dulezite pravidlo:
`Reconciliation` je samostatny use-case. Jeho smyslem neni menit pravdu, ale odhalit, kde se interni model rozesel s externi realitou a vyvolat korektni opravu pres definovany proces.

---

### Read Models

Ucel:
Vraci read-side pohledy optimalizovane pro frontend, reporting a agregace. Tato skupina modulu nesmi vytvaret vlastni alternativni business pravidla. Ma pouze skladat data z canonical domen.

Source of truth:

- zadna primarni data nevlastni,
- je to cteci vrstva slozena nad holdings, snapshots, prices/FX a account metadata.

Podmoduly:

- `Portfolio Read Model`
- `Dashboard Read Model`
- budouci `Reports Read Model`
- budouci `Analytics Read Model`

Spolecna pravidla:

- vsechny read modely musi sdilet stejnou definici financnich hodnot,
- read modely nesmi obchazet canonical pravidla ledgeru, snapshotu nebo FX,
- kdyz dve view vraceji stejnou metriku, musi ji brat ze stejneho business zakladu.

#### Portfolio Read Model

Patri sem:

- aktualni portfolio response,
- pozice,
- cash breakdown,
- invested/deposited,
- realized/unrealized P&L,
- warnings a quality flags.

Nepatri sem:

- parser logika,
- canonical ledger storage,
- market data storage,
- auth/session.

Tento modul smi zapisovat:

- maximalne read-side cache, pokud bude zavedena a explicitne vlastnena.

Tento modul smi cist:

- accounts,
- holdings,
- snapshots,
- prices/FX,
- ledger summary data.

Tento modul nesmi:

- zavest druhou definici portfolio cisel,
- potichu obchazet snapshot a FX pravidla.

#### Dashboard Read Model

Ucel:
Vraci globalni prehled financni situace uzivatele nebo vybrane skupiny uctu.

Patri sem:

- account overview,
- net worth summary,
- high-level trend data,
- dashboard widgets a agregace.

Nepatri sem:

- canonical transaction history,
- parser pravidla,
- holdings persistence.

Tento modul smi cist:

- accounts,
- net worth snapshots,
- account snapshots,
- portfolio read models,
- pripadne bankovni transakce, pokud dashboard zobrazuje i cashflow.

Tento modul nesmi:

- mit vlastni odlisnou definici hodnot oproti portfoliu,
- znovu pocitat to same jinymi pravidly jen pro dashboard.

---

### Notifications

Ucel:
Spravuje systemove a uzivatelske notifikace vyvolane backendovymi udalostmi.

Source of truth:

- notification definitions,
- delivery state,
- user-visible notification history, pokud se bude ukladat.

Patri sem:

- import completed/failed notifikace,
- snapshot failure notifikace,
- budouci operational nebo user-facing upozorneni.

Nepatri sem:

- samotna business logika importu, snapshotu nebo auth,
- rozhodovani o financnich hodnotach.

Tento modul smi cist:

- stav jobu,
- import batch vysledky,
- snapshot a audit udalosti.

Tento modul nesmi:

- menit canonical domenova data jen kvuli notifikaci.

---

### Audit

Ucel:
Drzi auditni stopu zmen a kritickych systemovych udalosti.

Source of truth:

- kdo zmenil co,
- kdy k tomu doslo,
- jaky proces nebo job zmenu zpusobil,
- historie importu a dohledatelne zmeny canonical dat, pokud se rozhodneme je auditovat.

Patri sem:

- audit zaznamy,
- change metadata,
- import historie a operacni audit,
- dohledatelnost backendovych zasahu.

Nepatri sem:

- samotna canonical data domen,
- parser transform logika,
- read model aggregate logika.

Tento modul smi cist:

- udalosti z ostatnich modulu pres definovane audit kontrakty.

Tento modul nesmi:

- byt tajnou druhou databazi business stavu,
- nahrazovat import batch, ledger nebo snapshots jako source of truth.

---

### Auth and Identity

Ucel:
Spravuje uzivatelskou identitu, session a pristupova pravidla.

Source of truth:

- user identity,
- session state,
- access boundary.

Patri sem:

- login,
- session bridge mezi frontendem a backendem,
- user/account authorization,
- security boundary.

Nepatri sem:

- portfolio vypocty,
- import parsing,
- prices a FX.

Tento modul smi cist:

- account ownership vazby.

Tento modul nesmi:

- drzet financni read modely,
- zavislostmi zatahovat business logiku do auth vrstvy.

---

### Jobs and Background Processing

Ucel:
Spousti pomale nebo asynchronni workflow mimo request-response cyklus.

Source of truth:

- job status,
- retry state,
- operational metadata.

Patri sem:

- import post-processing,
- snapshot rebuild,
- price/FX backfill,
- dlouhe recalculation workflow.

Nepatri sem:

- vlastni business pravidla oddelena od domenovych modulu.

Tento modul smi:

- orchestracne volat imports, ledger, snapshots, notifications a prices/FX.

Tento modul nesmi:

- zavadet vlastni obchodni logiku bokem jen proto, ze bezi na backgroundu.

---

### Shared

Ucel:
Obsahuje pouze technicke sdilene stavebni bloky, ktere nejsou vlastnictvim konkretni domeny.

Smi obsahovat pouze:

- logging,
- konfiguraci,
- common types,
- errors,
- technicke helpery bez domenove semantiky.

Nesmi obsahovat:

- obchodni logiku,
- portfolio vypocty,
- parser-specific pravidla,
- auth rozhodovaci logiku,
- "jen docasne" cross-domain utility, ktere ve skutecnosti patri do konkretni domeny.

Explicitni pravidlo:

- nevytvaret `shared/utils.py` nebo ekvivalent jako odkladiste nahodne business logiky,
- pokud helper potrebuje znat domenovy vyznam dat, nepatri do `Shared`, ale do konkretniho modulu.

---

## Kam co patri

### Kdyz pridavam novy CSV import

Patri do:

- `Parsers` pro transform logiku,
- `Imports` pro batch, audit, status a orchestrace,
- `Ledger` pro vznik canonical eventu a movementu.

Nepatri do:

- `Read Models`,
- `Snapshots`,
- `Frontend`.

### Kdyz pridavam novy vypocet portfolio hodnoty

Patri do:

- `Read Models`, pokud jde o aktualni cteci skladani dat,
- `Snapshots`, pokud jde o historickou ulozenou valuaci,
- `Prices and FX`, pokud je potreba nova cenova nebo FX zavislost.

Nepatri do:

- `Accounts`,
- `Parsers`,
- `Frontend component`.

### Kdyz pridavam novy typ financni udalosti

Patri do:

- `Ledger` jako canonical udalost a movement pravidla,
- `Parsers`, pokud ji umi nacist externi zdroj,
- `Snapshots` a `Read Models`, pokud ovlivni valuaci nebo zobrazeni.

Nepatri do:

- `Holdings` jako primarni misto definice udalosti.

### Kdyz pridavam corporate action

Patri do:

- `Corporate Actions` pro definici a mapovani trzni udalosti,
- `Ledger`, pokud se ma corporate action projevit canonical udalosti a movementy,
- `Assets`, pokud je potreba nova asset/listing identita po mergeru nebo spin-off.

Nepatri do:

- `Prices and FX` jako jedine misto pravdy o splitu nebo mergeru,
- `Holdings` jako tiche prepsani mnozstvi bez historie.

### Kdyz resim rozdil mezi aplikaci a brokerem

Patri do:

- `Reconciliation` pro detekci a vyhodnoceni driftu,
- `Ledger` nebo `Imports`, pokud se nasledne potvrdi potreba canonical opravy.

Nepatri do:

- `Holdings` jako misto, kde se rozdil rucne premaze bez historie,
- `Snapshots` jako misto, kde se chyba jen zamaskuje.

### Kdyz pridavam novou asset identitu nebo listing

Patri do:

- `Assets`.

Nepatri do:

- `Prices and FX`,
- `Ledger`,
- `Holdings`.

### Kdyz pridavam novou cenu nebo FX provider logiku

Patri do:

- `Prices and FX`.

Nepatri do:

- `Snapshots`,
- `Read Models`,
- `Frontend`.

### Kdyz pridavam novy graf nebo widget

Patri do:

- `Frontend`,
- pripadne `Read Models`, pokud je potreba novy backend response shape.

Nepatri do:

- `Ledger`,
- `Parsers`,
- `Accounts`.

### Kdyz pridavam novy account-level prehled

Patri do:

- `Read Models`,
- `Accounts`, pokud jde o metadata uctu.

Nepatri do:

- `Snapshots` jako presentation-only vrstva bez duvodu,
- `Frontend` jako misto, kde se cela logika spocita ad hoc.

### Kdyz pridavam audit nebo notifikace

Patri do:

- `Audit`, pokud jde o dohledatelnost a zaznam zmen,
- `Notifications`, pokud jde o user-facing nebo operational upozorneni.

Nepatri do:

- `Shared`,
- `Read Models`,
- `Frontend` jako source of truth pro tyto udalosti.

---

## Povinne hranice mezi moduly

- `Parsers` nikdy nesmi zapisovat primo do portfolio nebo snapshot tabulek.
- `Imports` nikdy nesmi definovat vlastni alternativni business pravidla k ledgeru.
- `Imports` musi garantovat idempotenci opakovanych importu.
- `Holdings` nikdy nesmi byt jediny zdroj historie.
- `Snapshots` nikdy nesmi byt jediny zdroj toho, co se skutecne stalo.
- `Read Models` musi sdilet stejna financni pravidla.
- `Frontend` nikdy nesmi zavest vlastni alternativni vypocet k backendu.
- `Prices and FX` nikdy nesmi drzet user-specific business stav.
- `Assets` vlastni asset identitu; ostatni moduly ji jen referencuji.
- `Corporate Actions` nesmi menit portfolio stav bez canonicalho dopadu do `Ledgeru`.
- `Reconciliation` nesmi potichu opravovat drift bez explicitni opravne cesty.
- `Ledger` musi zustat append-only.
- `Auth` nikdy nesmi byt obalenim pro business logiku, ktera patri do jinych modulu.
- `Shared` nikdy nesmi rust do neformalniho business modulu.

---

## Rozhodovaci pravidlo pri nejasnosti

Kdyz nebude jasne, kam nova vec patri, rozhoduje se v tomto poradi:

1. Je to primarni zaznam toho, co se stalo?
   Pak to patri do `Ledger`, `Accounts`, `Assets`, `Audit` nebo `Imports`.
2. Je to odvozene z primarnich dat?
   Pak to patri do `Holdings`, `Snapshots` nebo `Read Models`.
3. Je to referencni trzni nebo kurzove data?
   Pak to patri do `Prices and FX`.
4. Je to jen prezentace nebo interakce?
   Pak to patri do `Frontend`.
5. Je to pomala orchestrace?
   Pak to patri do `Jobs`, ale bez vytvareni nove business logiky bokem.
6. Je to jen technicka sdilena pomucka?
   Pak to patri do `Shared`, ale jen pokud nema domenovy vyznam.

---

## Dlouhodoby cil

Tento modulovy model ma zajistit, ze:

- aplikace poroste bez architektonickeho chaosu,
- business logika zustane centralizovana a dohledatelna,
- nove parsery, read modely a klienti pujde pridavat bez rozbiti zakladu,
- prechod vypocetne tezke logiky do `Rustu` pujde udelat bez zmeny produktovych hranic.
