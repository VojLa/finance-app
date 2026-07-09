# DB audit a navrh pevneho zakladu

Datum auditu: 2026-06-14

Tento dokument shrnuje chyby, nejasnosti a rizika v aktualnim Prisma/PostgreSQL modelu. Cilem je pripravit DB na dlouhodoby vyvoj a vyssi pocet uzivatelu.

## Hlavni zaver

Schema je pouzitelne pro MVP, ale neni jeste pevny zaklad pro vetsi objem dat. Nejvetsi problemy nejsou v jednotlivych sloupcich, ale v hranicich datoveho modelu:

- chybi indexy pro vetsinu beznych dotazu podle `userId`, `accountId`, `date`, `symbol`, `timestamp`;
- neni jasne oddeleny source of truth od cache;
- investicni transakce, cash transakce, holdings a snapshoty maji prekryv odpovednosti;
- `Asset` je globalni, ale `symbol` sam o sobe neni stabilni globalni identifikator;
- historicka data a prodane pozice se maji rekonstruovat z transakci, ne z aktualnich holdings;
- multi-user provoz bude vyzadovat silnejsi tenant scoping, audit trail a background joby.

## Source of truth vs cache

Navrhovane pravidlo:

- `Transaction` je source of truth pro bankovni/cash pohyby.
- `InvestmentTransaction` je source of truth pro investicni pohyby.
- `ImportBatch` + `ImportRow` jsou source of truth pro importni audit.
- `Asset`, `AssetAlias`, `PriceSnapshot`, `ExchangeRate` jsou referencni/market data.
- `Holding` je cache aktualni pozice, dopoctitelna z `InvestmentTransaction`.
- `PortfolioSnapshot`, `PortfolioSnapshotItem`, `NetWorthSnapshot` jsou cache historickych casovych rad.

Prakticky dusledek:

- cache tabulky musi mit `calculatedAt`, pripadne `sourceVersion` nebo `calculationVersion`;
- musi existovat backfill/recalculate job, ktery cache umi zahodit a znovu postavit;
- UI nesmi brat cache jako jediny zdroj pravdy pro historii.

## Kriticke problemy

### 1. Chybi indexy pro skalovani

Aktualni schema ma hlavne primarni a unikatni indexy. Pro velky objem budou pomale dotazy typu:

- transakce uctu serazene podle data;
- import deduplikace podle `externalId`;
- portfolio historie podle `userId`, `timestamp`, `granularity`;
- price lookup podle `assetId`, `timestamp`;
- holdings podle `accountId`;
- import rows podle batch/status;
- budget podle user/period.

Doporucene indexy:

```prisma
@@index([userId])
@@index([accountId, date])
@@index([accountId, externalId])
@@index([accountId, type, date])
@@index([userId, createdAt])
@@index([assetId, timestamp])
@@index([symbol])
@@index([snapshotId])
@@index([importBatchId, rowNumber])
@@index([importBatchId, status])
```

Konkretni modely k doplneni:

- `Account`: `@@index([userId])`
- `AccountShare`: `@@index([ownerId])`, `@@index([sharedWithId])`
- `Transaction`: `@@index([accountId, date])`, `@@index([accountId, externalId])`, `@@index([categoryId, date])`, `@@index([importBatchId])`
- `InvestmentTransaction`: `@@index([accountId, date])`, `@@index([accountId, symbol, date])`, `@@index([accountId, externalId])`, `@@index([assetId, date])`, `@@index([importBatchId])`
- `Holding`: `@@index([accountId])`, `@@index([assetId])`
- `PriceSnapshot`: `@@index([assetId, timestamp])`
- `ExchangeRate`: `@@index([fromCurrency, toCurrency, date])`
- `ImportRow`: `@@index([importBatchId, rowNumber])`, `@@index([importBatchId, status])`
- `PortfolioSnapshot`: `@@index([userId, granularity, timestamp])`
- `PortfolioSnapshotItem`: `@@index([accountId])`, `@@index([assetId])`
- `NetWorthSnapshot`: `@@index([userId, date])`

### 2. Globalni `Asset.symbol @unique` je moc slabe

`Asset.symbol` je globalne unikatni. To je jednoduche, ale do budoucna problem:

- stejny ticker muze existovat na vice burzach;
- ETF ma vice listing aliasu (`VUAA.DE`, `VUAA.L`, `VUAA.MI`);
- crypto symboly nejsou globalne unikatni;
- nektere assety maji primarni identifikator ISIN, jine CoinGecko id.

Doporuceni:

- zrusit predstavu, ze `symbol` je jediny globalni identifikator;
- pridat pole jako:
  - `canonicalSymbol`
  - `isin`
  - `exchange`
  - `mic`
  - `country`
  - `providerKey`
- povolit vice aliasu pro jednoho providera.

Problem v aktualnim modelu:

```prisma
@@unique([assetId, provider])
```

To neumozni vice Yahoo aliasu pro jeden asset. Lepsi:

```prisma
@@unique([provider, externalId])
@@index([assetId, provider])
```

### 3. `Holding` micha aktualni pozici a market cache

`Holding` obsahuje:

- quantity, avgBuyPrice = vypocet z transakci;
- currentPrice, currentValue, unrealizedPnl = market cache;
- realizedPnl = spis agregace z transakci.

To zpusobuje nejasnosti:

- v jake mene je `currentValue`?
- kdy byla cena aktualizovana?
- co znamena `realizedPnl` na holding, kdyz prodana pozice muze zmizet?

Doporuceni:

- `Holding` nechat jako aktualni pozici:
  - quantity
  - avgCost
  - costCurrency
  - accountId
  - assetId
  - calculatedAt
- market hodnoty drzet bud v `PriceSnapshot`, nebo v oddelene cache tabulce napr. `HoldingValuation`.
- `realizedPnl` drzet jako agregaci z `InvestmentTransaction` nebo samostatny realized ledger.

### 4. `InvestmentTransaction` je prilis volny model

Mnoho poli je nullable, coz je flexibilni, ale DB negarantuje konzistenci.

Priklady:

- `buy/sell` by mely mit asset/quantity/price nebo total;
- `dividend/interest` nepotrebuji quantity;
- `currency_conversion` potrebuje dve meny a kurz;
- `fee` muze byt samostatna transakce nebo atribut jine transakce.

Doporuceni:

- bud ponechat volny model, ale pridat aplikační validaci + testy;
- nebo zavest explicitnejsi model:
  - `InvestmentOrder`
  - `InvestmentTransaction`
  - `CashMovement`
  - `AssetMovement`
  - `Fee`

Pro vetsi robustnost je nejlepsi ledger pristup: kazda udalost se rozpadne na pohyby aktiv/cash.

### 5. Bankovni `Transaction` nepodporuje splity

Ve specifikaci se pocita s rozdelenim transakce na vice kategorii, ale aktualni schema nema `TransactionSplit`.

Doporuceni:

- pridat `TransactionSplit`;
- `Transaction.categoryId` brat jako rychly single-category shortcut nebo ho casem nahradit splity.

### 6. U `ImportBatch` je deduplikace na file checksum moc hruba

Aktualne:

```prisma
@@unique([userId, accountId, checksum])
```

To zachyti stejny soubor, ale ne robustne jednotlive radky napric soubory.

Doporuceni:

- `ImportRow.deduplicationKey` udelat povinny pro uspesne radky;
- pridat unikatni index podle zdroje/accountu:
  - `@@unique([importBatchId, rowNumber])`
  - globalnejsi dedupe tabulku nebo index podle `accountId/source/externalId`;
- u `Transaction` a `InvestmentTransaction` pridat unique per account/source/externalId, pokud provider externe ID garantuje.

### 7. Snapshoty jsou cache, ale nemaji invalidacni metadata

`PortfolioSnapshot` ma `isRecalculated`, ale ne:

- `calculatedAt`;
- `calculationVersion`;
- `inputsHash`;
- `rangeStart/rangeEnd`;
- info, jestli je hodnota z live/historical/manual/fallback ceny.

Doporuceni:

- pridat `calculatedAt`;
- pridat `calculationVersion`;
- u `PortfolioSnapshotItem` pridat:
  - `priceCurrency`
  - `priceSource`
  - `priceTimestamp`
  - `costBasis`
  - `costCurrency`

### 8. Mazani a archivace nejsou sjednocene

Nektere vazby maji `onDelete: Cascade`, jine `Restrict`, jine `SetNull`.

Rizika:

- smazani uctu muze selhat kvuli restrict vazbam;
- smazani assetu smaze price snapshots, coz muze znicit historicka data;
- import batch cascade smaze audit, pokud se smaze ucet.

Doporuceni:

- user/account se spise archivuje nez maze;
- market data (`Asset`, `PriceSnapshot`) nemazat cascade kvuli historii;
- osobni data mazat podle GDPR flow oddelene.

### 9. Chybi tenant-aware constraints

Cast modelu ma `userId`, cast jen `accountId`.

To neni nutne spatne, ale pro multi-user provoz:

- vsechny dotazy musi jit pres account access;
- DB sama nebrani spatnemu napojeni napr. `ImportBatch.userId` vs `Account.userId`;
- `Category.userId` a default category mohou byt napojene nejasne.

Doporuceni:

- u citlivych entit zvazit redundantni `userId` pro jednodussi RLS/partitioning;
- nebo v Postgres zapnout Row Level Security pozdeji;
- minimalne pridat indexy podle tenant klicu.

## Stredni problemy a nejasnosti

### Kategorie

- `Category.userId` je nullable kvuli default kategoriim.
- Chybi unique constraint na user/name/parent/type.
- Default kategorie pres pevne ID muze byt problem pri lokalizaci a vice jazycich.

### Budget

- `Budget` ma `month/year` i `periodType`, ale unique constraint funguje jen pro mesicni rozpocty.
- Pro weekly/yearly/custom bude potreba `periodStart`, `periodEnd`.

### Counterparty

- Chybi unique/index pro `userId, name`.
- Alias nema index na `counterpartyId`.
- Match pravidla mohou byt draha bez normalizovaneho textu.

### ExchangeRate

- `date` by mela byt normalizovana na den.
- Chybi jasne pravidlo, jestli rate znamena `from -> to` za 1 jednotku nebo za mnozstvi.

### PriceSnapshot

- Historicke ceny mohou byt obrovska tabulka.
- Bude potreba retention/partitioning strategie.
- Pro velky objem zvazit denni OHLC tabulku misto jedineho `price`.

### IDs

- `cuid()` je v poradku pro MVP.
- Pro velky system stoji za zvazeni UUIDv7 kvuli index locality a casovemu razeni.

## Navrh ciloveho smeru DB

### Minimalni stabilizace

1. Pridat indexy.
2. Upravit `AssetAlias` unique constraint.
3. Pridat `TransactionSplit`.
4. Pridat metadata pro snapshoty a valuation.
5. Pridat backfill joby.

### Robustnejsi investicni model

Z dlouhodobeho hlediska zvazit ledger:

- `InvestmentEvent`: importovana udalost/order/dividenda/smena.
- `InvestmentMovement`: pohyb assetu nebo meny.
- `InvestmentTransaction`: optional view/compat layer.
- `Holding`: materialized current state.
- `RealizedPnl`: materialized realized ledger.

To umozni prirozene reprezentovat:

- Anycoin multi-row obchod;
- Trading212 currency conversion;
- dividendy;
- poplatky;
- presuny mezi ucty;
- cash zustatky;
- castecnou a uplnou realizaci pozice.

## Doporučene poradi

1. Pridat chybejici indexy bez zmeny business logiky.
2. Opravit `Asset`/`AssetAlias` model pro providery a vice aliasu.
3. Pridat `TransactionSplit`.
4. Ujasnit `Holding` jako cache a pridat `calculatedAt`.
5. Ujasnit `PortfolioSnapshotItem` hodnoty a pridat price metadata.
6. Navrhnout investicni ledger jako dalsi migraci, ne ho lepit postupne do nullable poli.
7. Teprve potom optimalizovat API a UI nad stabilnim modelem.

## Kratke shrnuti pro rozhodnuti

Soucasna DB neni spatna pro prototyp. Pro produkcni viceuzivatelskou appku je ale potreba nejdriv udelat DB hardening:

- indexy;
- tenant hranice;
- jasne cache/source-of-truth oddeleni;
- robustni asset aliasy;
- historicke snapshot metadata;
- split transakce;
- pozdeji investicni ledger.

Bez toho bude kazda dalsi funkcionalita, hlavne historicke portfolio a velke importy, narazet na vykon a nejasnou semantiku dat.

## Rozhodovaci otazky pred dalsi DB fazi

Tyto odpovedi potrebuji pred dalsimi vetsimi migracemi:

1. Investicni vypocet:
   - Chces pro P&L a cost basis prumernou nakupni cenu, FIFO, nebo pozdeji volitelne oboji?
   - Pokud nevis, doporuceni pro MVP je prumerna cena, ale schema pripravit tak, aby FIFO slo doplnit.

2. Investicni model:
   - Chceme zustat u jedne tabulky `InvestmentTransaction`, nebo prejit na ledger model `InvestmentEvent` + `InvestmentMovement`?
   - Doporuceni pro dlouhodoby velky objem je ledger, ale je to vetsi refaktor.

3. Mazani dat:
   - Maji se ucty/transakce fyzicky mazat, nebo jen archivovat/soft-delete?
   - Pro produkci a audit doporucuji archivovat, fyzicke mazani resit jen jako GDPR flow.

4. Multi-user a sdileni:
   - Ma byt sdileni uctu jen mezi existujicimi uzivateli, nebo pozdeji pres pozvanky na email?
   - Pokud pozvanky, bude potreba `AccountInvite`.

5. Assety:
   - Chces assety globalni pro vsechny uzivatele, nebo uzivatelsky editovatelne kopie?
   - Doporuceni: globalni canonical asset + user/account level overrides jen pro aliasy/manual cenu.

6. Historicka data:
   - Jak dlouho drzet historicke ceny a snapshoty?
   - Doporuceni: price snapshots dlouhodobe, portfolio snapshots agregovat podle granularity.

7. Import audit:
   - Chces uchovavat raw import rows navzdy, nebo po case mazat/anonymizovat?
   - Pro debug je dobre je drzet, ale pri velkem objemu bude potreba retention policy.

8. Meny:
   - Ma byt base currency vzdy per user, nebo per household/shared workspace?
   - Pokud se bude appka sdilet v rodine, mozna bude lepsi zavest workspace/household entitu.

## Rozhodnuti ze dne 2026-06-14

- P&L: DB ma byt pripravena na budouci FIFO. MVP muze docasne pocitat prumer, ale schema nesmi FIFO znemoznit.
- Investice: model se bude delit na udalosti a pohyby. Cilovy smer je ledger (`InvestmentEvent` + `InvestmentMovement`), ne dalsi rozsireni jedne nullable tabulky.
- Mazani: bezne uzivatelske mazani bude archivace/soft-delete. Fyzicke mazani se pouzije jen pro GDPR flow.
- Assety: assety budou globalni. Jeden asset muze mit vice podob/listingu/symbolu podle burzy, providera, exchange nebo konkretniho tickeru.
- Import raw data: raw import rows se nebudou drzet navzdy. Bude potreba retention policy.
- Sdileni: budou podporovane i pozvanky pres email, nejen sdileni existujicim uzivatelum.
- Base currency: zustava per user a slouzi primarne jako zobrazovaci/prepocitaci preference. Account, asset, transaction a price data musi mit vlastni konkretni menu.
- Migrace: protoze v aplikaci nejsou data, nema smysl pridavat dalsi migrace. Aktualni schema se muze srovnat do ciste init migrace.
