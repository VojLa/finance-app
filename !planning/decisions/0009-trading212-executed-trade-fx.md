# ADR 0009 - Trading212 executed trade FX and fee separation

Status: Accepted
Date: 2026-08-10
Decision owners: vlastnik finance-app
Supersedes: none
Superseded by: none

## Kontext

Trading212 exportuje u preshranicniho obchodu mnozstvi, burzovni cenu v mene
listingu, vyporadanou `Total` v mene uctu, samostatny poplatek a redundantni
`Exchange rate`. Neexportuje pritom samostatne `Currency conversion from/to`
legs. Puvodni normalizer kazdy samostatny kurz omylem povazoval za menovou
konverzi a korektni nakupy proto posilal do `needs_review`.

`Total` ma navic jinou settlement semantiku podle smeru obchodu: u nakupu je
castkou skutecne odepsanou vcetne poplatku, u prodeje je cistym prijmem po
odecteni poplatku. Zapsat `Total` a stejny poplatek jako dva nezavisle pohyby by
poplatek zapocital dvakrat.

## Rozhodnuti

Pro `buy` a `sell` je autoritou provedena transakce, nikoli redundantni sloupec
`Exchange rate`.

- nakupni jistina = `settled Total - fee`;
- hruby vynos prodeje = `settled Total + fee`;
- implicitni prime FX = `quantity * quoted unit price / trade principal`, v
  orientaci settlement mena -> listing mena;
- chybejici nebo nulovy poplatek ponecha jistinu rovnu `Total`;
- nenulovy poplatek musi mit stejnou menu jako `Total`, jinak radek vyzaduje
  kontrolu;
- vysledna jistina musi byt kladna.

Samostatny kladny `Exchange rate` na trade radku je pouze redundantni vstupni
evidence. Nevytvari `conversion` objekt ani dalsi cash legs. Skutecna
`currency_conversion` akce nadale vyzaduje obe explicitni conversion legs.

Canonical ledger zapise asset a cash trade leg v presne vypoctene jistine a
poplatek jako samostatny fee leg. Jejich soucet/rozdil proto presne reprodukuje
provider settlement. Burzovni mena zustava listing identity. Odvozena jednotkova
porizovaci/prodejni hodnota v settlement mene se na hranici `NUMERIC(28,10)`
zaokrouhli deterministicky metodou decimal half-even; presna jistina se
nezaokrouhluje.

## Dusledky

- Preshranicni Trading212 nakupy a prodeje nepotrebuji fiktivni conversion legs.
- Poplatek se neuctuje dvakrat.
- Holding cost currency odpovida skutecne vyporadane mene, zatimco Listing si
  zachova burzovni menu.
- Neplatna desetinna hodnota, neslucitelna mena poplatku nebo nekladna jistina
  stale selze fail-closed jako `needs_review`.
- Stare terminalni import batch radky se automaticky neprepisuji; oprava se
  projevi pri novem cistem importu.

## Zamitnute alternativy

- Vyžadovat conversion legs u trade radku: Trading212 je pro tento typ obchodu
  neposkytuje.
- Pouzit provider `Exchange rate` jako jedinou autoritu: nereprodukuje sam o
  sobe presne cash settlement a fee.
- Zapsat provider `Total` i fee beze zmeny: poplatek by byl v cash historii
  dvakrat.
- Prevyst burzovni cenu na settlement menu a zahodit listing menu: znicilo by
  provider/listing identitu potrebnou pro market data.

## Migracni nebo rollout plan

1. Upravit cisty Trading212 normalizer a regression fixtures.
2. Odvodit canonical trade unit value z jistiny a mnozstvi pri tvorbe movement
   planu.
3. Overit normalize -> classify -> post -> Holding rebuild nad PostgreSQL.
4. Znovu importovat terminalni batch data; historicke raw radky zustavaji
   auditovatelne a nemeni se na miste.
