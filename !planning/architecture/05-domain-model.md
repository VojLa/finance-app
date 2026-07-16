# Domain Model

## Smysl dokumentu

Tento dokument popisuje hlavni entity systemu, jejich ucel, vlastnika, vztahy, zivotni cyklus a invariants. Je to referencni dokument pro navrh DB, backend logiky a API kontraktu.

Pokud `03-modules.md` rika, kdo co vlastni, `05-domain-model.md` rika, jaka data vubec existuji.

---

## Zakladni pravidla

- Canonical historie patri do domenovych entit, ne do read modelu.
- Read modely a snapshoty jsou odvozene vrstvy.
- Kazda entita ma jednoho hlavniho vlastnika.
- Vztahy musi byt odvoditelne z produktu, ne jen z technicke implementace.
- Invarianty jsou stejne dulezite jako samotna pole.

## Terminology lock

- `LedgerEvent` je canonical udalost
- `LedgerMovement` je atomicky pohyb uvnitr canonical udalosti
- `Holding` je aktualni odvozeny stav
- `AccountSnapshot` je historicky point-in-time stav jednoho uctu
- `NetWorthSnapshot` je agregovany point-in-time stav napric ucty
- `Read Models` je skupina ctecich projekci jako `Portfolio Read Model` a `Dashboard Read Model`
- `Institution` je identita zdroje importu
- `Asset` je canonical identita aktiva
- `AssetListing` je konkretni obchodovatelna nebo provider-specific podoba aktiva

---

## Hlavni entity

### User

Ucel:
Predstavuje identitu uzivatele a vlastnika osobnich financnich dat.

Vlastnik:
`Auth and Identity`

Vztahy:

- ma vice `Account`
- ma vice `ImportBatch`
- ma portfolio a dashboard read modely

Zivotni cyklus:

- vznik registraci
- aktivni pouzivani
- archivace nebo smazani podle budouci retention a GDPR politiky

Invarianty:

- uzivatel nesmi videt data jineho uzivatele
- vsechny account-level operace musi byt autorizovane pres vztah k `User`

### Account

Ucel:
Financni kontejner pro banku, broker, wallet nebo jiny zdroj financnich dat.

Vlastnik:
`Accounts`

Vztahy:

- patri jednomu nebo vice uzivatelum podle budouci ownership politiky
- ma vice `ImportBatch`
- ma vice `LedgerEvent`
- ma aktualni `Holding`
- ma vice `AccountSnapshot`

Zivotni cyklus:

- vytvoreni
- aktivni pouzivani
- archivace
- pripadne smazani

Invarianty:

- kazdy ucet ma hlavni menu
- account-level hodnoty se zobrazuji v hlavni mene uctu

### Institution

Ucel:
Logicka identita banky, brokera, smenarny nebo jine financni instituce.

Vlastnik:
`Imports` a castecne `Accounts`

Vztahy:

- muze mit vice parseru nebo exportnich variant
- muze byt navazana na vice uctu ruznych uzivatelu

Zivotni cyklus:

- pridani do katalogu podporovanych instituci
- rozsireni o nove exportni varianty
- pripadne deaktivace nebo oznaceni, ze exportni format je zastaraly

Invarianty:

- parser pravidla se musi vazat ke konkretni instituci nebo exportnimu formatu
- jedna instituce muze mit vice exportnich variant a vice parser pravidel v case

### ImportBatch

Ucel:
Predstavuje jednu importni davku a je source of truth pro audit importu.

Vlastnik:
`Imports`

Vztahy:

- patri k `User`
- typicky patri k jednomu `Account`
- obsahuje vice `ImportRow`
- vede k vytvoreni canonical udalosti v `Ledger`

Zivotni cyklus:

- created
- processing
- completed
- failed

Invarianty:

- batch musi byt dohledatelny
- opakovany import stejneho souboru nesmi bez kontroly vytvaret duplicity

### ImportRow

Ucel:
Auditni zaznam o konkretnim radku vstupniho exportu.

Vlastnik:
`Imports`

Vztahy:

- patri do `ImportBatch`
- muze vest k nule nebo vice canonical zmenam

Zivotni cyklus:

- parsed
- skipped
- unsupported
- failed

Invarianty:

- nepodporovany radek nesmi zmizet bez stopy

### LedgerEvent

Ucel:
Canonical financni udalost, ktera rika, co se skutecne stalo.

Vlastnik:
`Ledger`

Vztahy:

- patri k `Account`
- ma vice `LedgerMovement`
- muze byt navazana na `ImportBatch`
- muze odkazovat na `Asset` nebo `AssetListing`

Zivotni cyklus:

- vytvoreni z importu, corporate action nebo manualni operace
- pripadna kompenzacni oprava novou udalosti

Invarianty:

- `LedgerEvent` je append-only
- historicka chyba se neopravuje tichym update, ale kompenzacni udalosti

### LedgerMovement

Ucel:
Atomicky pohyb assetu, cash, fee, dane nebo jine hodnoty v ramci jedne udalosti.

Vlastnik:
`Ledger`

Vztahy:

- patri do `LedgerEvent`
- muze odkazovat na `Asset`, `AssetListing` a menu

Zivotni cyklus:

- vznik spolu s `LedgerEvent`
- pozdeji se nemeni mimo explicitni append-only opravnou strategii

Invarianty:

- soucet movementu musi odpovidat semantice nadrazene udalosti

### Holding

Ucel:
Aktualni odvozeny stav pozice nebo cash na uctu.

Vlastnik:
`Holdings`

Vztahy:

- patri k `Account`
- typicky se vztahuje k `AssetListing`

Zivotni cyklus:

- recalculated z `Ledger`
- prubezne aktualizovan

Invarianty:

- neni source of truth pro historii
- musi byt odvoditelny z ledgeru

### AccountSnapshot

Ucel:
Point-in-time historicky stav uctu v jeho hlavni mene.

Vlastnik:
`Snapshots`

Vztahy:

- patri k `Account`
- ma vice `AccountSnapshotItem`

Zivotni cyklus:

- build nebo rebuild
- pouziti pro historicke grafy a live continuation

Invarianty:

- snapshot je odvozeny z ledgeru, holdings seedu, prices a FX
- pri konfliktu ma pravdu ledger

### AccountSnapshotItem

Ucel:
Detail jednotlivych pozic uvnitr snapshotu.

Vlastnik:
`Snapshots`

Vztahy:

- patri do `AccountSnapshot`
- vztahuje se k `Asset` nebo `AssetListing`

Invarianty:

- musi jit vysvetlit pres pozici, cenu a kurz daneho dne

### NetWorthSnapshot

Ucel:
Historicka agregace ciste hodnoty napric ucty.

Vlastnik:
`Snapshots`

Vztahy:

- patri k `User`
- muze byt odvozena z vice `AccountSnapshot`

Invarianty:

- neni primarni zdroj account-level pravdy

### Asset

Ucel:
Canonical identita aktiva, napr. Apple, Bitcoin nebo zlato.

Vlastnik:
`Assets`

Vztahy:

- ma vice `AssetListing`
- ma vice `AssetAlias`
- muze mit vice `PriceSnapshot`

Invarianty:

- jeden asset muze mit vice podob podle providera, symbolu nebo burzy
- globalni symbol sam o sobe nestaci jako jedina identita

### AssetListing

Ucel:
Konkretni obchodovatelna nebo provider-specific podoba assetu.

Vlastnik:
`Assets`

Vztahy:

- patri k `Asset`
- ma vice `PriceSnapshot`

Invarianty:

- listing reprezentuje konkretni kombinaci symbolu, exchange nebo providera

### PriceSnapshot

Ucel:
Historicka nebo live cena aktiva nebo listingu.

Vlastnik:
`Prices and FX`

Vztahy:

- patri k `Asset` nebo `AssetListing`

Invarianty:

- musi byt dohledatelny zdroj ceny
- neni user-specific

### ExchangeRate

Ucel:
Historicky nebo aktualni kurz mezi menami.

Vlastnik:
`Prices and FX`

Invarianty:

- kurz se pouziva podle data udalosti nebo snapshotu, ne nahodne podle dnesni hodnoty

### CorporateAction

Ucel:
Trzni udalost typu split, reverse split, merger nebo spin-off.

Vlastnik:
`Corporate Actions`

Vztahy:

- vztahuje se k `Asset` nebo `AssetListing`
- promita se do `LedgerEvent`

Zivotni cyklus:

- vznik z interni evidence, provider dat nebo manualniho potvrzeni
- validace, ze se vztahuje ke spravne asset identite
- projekce do canonical zmeny v `Ledger`
- archivace jako historicka trzni udalost

Invarianty:

- pokud meni ekonomickou realitu pozice, musi se nakonec projevit canonical zmenou v ledgeru
- nesmi existovat jen jako "informace bokem", pokud ma realny dopad do mnozstvi nebo cost basis

### ReconciliationRun

Ucel:
Odsouhlaseni interni pravdy aplikace s externi realitou.

Vlastnik:
`Reconciliation`

Vztahy:

- patri k `Account`
- porovnava `Holding`, `Ledger`, `AccountSnapshot` a externi statement

Zivotni cyklus:

- spusteni manualne nebo automaticky
- porovnani interniho stavu s externim statementem
- vznik findings a drift stavu
- oznaceni jako resolved, ignored nebo escalated podle dalsiho workflow

Invarianty:

- nesmi potichu menit canonical historii
- musi byt dohledatelne, podle jakych dat a ke kteremu okamziku porovnani probehlo

### Notification

Ucel:
Uzivatelska nebo systemova notifikace vyvolana udalosti.

Vlastnik:
`Notifications`

Zivotni cyklus:

- vznik z backendove udalosti nebo jobu
- queued nebo scheduled delivery
- delivered, failed nebo dismissed stav podle typu notifikace
- pripadna expirace nebo archivace

Invarianty:

- notifikace nesmi byt source of truth business stavu
- notifikace musi byt odvoditelna z udalosti, ne naopak

### AuditLog

Ucel:
Dohledatelna stopa zmen a operaci.

Vlastnik:
`Audit`

Zivotni cyklus:

- vznik pri zmene, importu, jobu nebo systemove udalosti
- ulozeni s metadaty o puvodu a case
- retention nebo archivace podle budouci politiky

Invarianty:

- audit nenahrazuje canonical data
- audit zaznam musi byt readonly z pohledu bezne business logiky

---

## Budouci entity

- `TaxLot` nebo `TaxEngineResult`
- `Report`
- `Budget`
- `Rule`
- `SharedAccess`

Tyto entity nejsou nutne pro aktualni MVP zaklad, ale je vhodne s nimi pocitat v dlouhodobe architekture.
