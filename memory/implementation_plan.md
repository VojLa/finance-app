# Plan postupu implementace

Tento dokument slouzi jako pracovni kostra pro dalsi vyvoj finance appky. Cilem je mit jasne poradi praci, aby se jednotlive casti neopravovaly izolovane a pozdeji se nemusely prekopavat.

## 1. Stabilizace zakladu

Cil: mit spolehlivy technicky zaklad, na kterem se da bezpecne pridavat domenova logika.

- Srovnat encoding textu v existujicich souborech, hlavne ceske texty a hlasky.
- Udrzet testovaci stack pres Vitest.
- Doplnovat testy k parserum, vypoctum portfolia a cenam.
- Zkontrolovat, ktere soubory jsou generovane nebo lokalni cache a nemaji byt commitovane.
- Vyresit opakovane warningy mimo domenu, napr. React hook warning v `accounts/page.tsx`.

Navazuje na:
- vsechny dalsi casti, protoze testy a citelny kod budou drzet zmeny pohromade.

## 2. Importy a parsery

Cil: nove zdroje dat pridavat predvidatelne a bez kopirovani logiky.

Hotovy smer:
- Parsery jsou rozdelene na dve skupiny:
  - single-row parsery: jeden CSV radek = jedna investicni transakce, napr. Trading 212.
  - grouped parsery: jedna investice/smena vznikne z vice radku, napr. Anycoin.

Dalsi kroky:
- Dopsat dokumentaci, jak pridat novy parser.
- Doplnit fixture CSV soubory pro realne exporty.
- Rozsirit testy o edge cases:
  - fee, dividendy, uroky, currency conversion.
  - castecne prodeje.
  - plne prodane pozice.
  - crypto deposit/withdrawal.
- U Raiffeisenbank poresit encoding a pripadne vice typu exportu.

Navazuje na:
- portfolio vypocty, protoze kvalita transakci rozhoduje o spravnych holdings a historii.

## 3. Portfolio pozice a P&L

Cil: aktualni portfolio musi byt spravne i po nakupu, prodeji, vkladu a vyberu.

Dalsi kroky:
- Zkontrolovat `recalculateHoldings` proti realnym scenarum.
- Rozhodnout, jestli zustaneme u prumerne nakupni ceny, nebo pozdeji pridame FIFO.
- Ukladat realizovane P&L konzistentne pri sell transakcich.
- Zachovat historii prodanych pozic pres transakce a snapshoty, ne pres aktualni `holding`.

Navazuje na:
- historicky graf portfolia.
- dashboard/net worth.
- danove reporty v budoucnu.

## 4. Live a historicke ceny

Cil: ceny maji byt rychle, cachovane a dohledatelne i pro evropske ETF.

Hotovy smer:
- Live ceny pro ETF/akcie jdou pres Yahoo chart endpoint.
- Crypto ceny jdou pres CoinGecko.
- Ceny se ukladaji do `PriceSnapshot`.
- Existuje zaklad pro aliasy symbolu, napr. `VUAA.DE`.

Dalsi kroky:
- Doplnit UI/admin misto pro rucni aliasy provideru.
- Doplnit manual price fallback pro assety, ktere API nezna.
- Nastavit cache pravidla:
  - live ceny kratky TTL.
  - historicke ceny dlouhy TTL.
  - nevolat externi API pri kazdem prekresleni grafu.
- Osetrit provider failures a zobrazit jasne warningy.

Navazuje na:
- portfolio hodnota.
- historicke grafy.
- snapshoty.

## 5. Historie portfolia a snapshoty

Cil: grafy musi umet zobrazit historii zpetne, vcetne starych prodanych pozic.

Hotovy smer:
- Historie se zacina dopocitavat z `InvestmentTransaction`, ne jen z aktualnich holdings.
- Podporovane rozsahy:
  - tyden
  - mesic
  - 3 mesice
  - 6 mesicu
  - 1 rok
  - vse
- Intervaly:
  - tyden a mesic: denni body.
  - 3M, 6M, 1Y: tydenni body.
  - vse: mesicni body.

Dalsi kroky:
- Optimalizovat vykon endpointu `/api/portfolio/history`.
- Neprepisovat snapshoty pri kazdem GET requestu, pokud nejsou zastarale.
- Pouzivat ulozene historicke ceny, pokud uz pokryvaji obdobi.
- Doplnit testy pro:
  - prodanou pozici, ktera se v historii zobrazi pred prodejem.
  - castecny prodej.
  - rozsahy a bucket intervaly.
  - account filter.

Navazuje na:
- UX grafu.
- rychlost aplikace.
- presnost historickych reportu.

## 6. Dashboard a net worth

Cil: dashboard, portfolio a cash cast maji pouzivat stejnou definici hodnot.

Dalsi kroky:
- Sjednotit vypocet cash, liabilities a portfolio value.
- Rozhodnout, kdy se ma pouzit live hodnota a kdy fallback na nakupni hodnotu.
- Net worth historii bud pocitat ze snapshotu, nebo rekonstruovat z transakci podobne jako portfolio.
- Zkontrolovat, aby investment cash movements nebyly zapocitane dvakrat.

Navazuje na:
- portfolio history.
- bankovni importy.
- budouci reporty.

## 7. UI a workflow

Cil: appka ma byt pouzitelna pro beznou praci, ne jen pro technicky import.

Dalsi kroky:
- Portfolio graf:
  - zrychlit prepinani rozsahu.
  - ukazat loading stav pro historii.
  - ukazat, jestli je bod grafu z live ceny, historicke ceny, nebo fallbacku.
- Import:
  - pridat preview pred ulozenim.
  - jasne zobrazit warnings a skipped rows.
  - nabidnout deduplikaci.
- Ceny:
  - tlacitko refresh.
  - stav posledni aktualizace.
  - varovani pro chybejici alias.

Navazuje na:
- vsechny domenove vypocty, protoze UI ma vysvetlovat jejich stav.

## 8. Doporučene poradi dalsi prace

1. Dodelat optimalizaci `/api/portfolio/history`, aby prepnuty rozsah netrval dlouho.
2. Pridat testy pro historickou rekonstrukci portfolia.
3. Doresit encoding ceskych textu v upravenych souborech.
4. Zvalidovat `recalculateHoldings` na realnych importech.
5. Dodelat dokumentaci pro pridani noveho parseru.
6. Pridat UI pro aliasy cenovych provideru.
7. Sjednotit dashboard/net worth vypocty s portfoliem.

## Otevrene otazky

- Chceme pro investice prumernou nakupni cenu, nebo FIFO?
- Ma se historicka hodnota portfolia pocitat podle close ceny v dane datum, nebo podle posledni dostupne ceny pred datem?
- Jak moc chceme cachovat historicke ceny a kdy je povazovat za zastarale?
- Maji se prodane pozice zobrazovat i v tabulce pozic jako archiv, nebo jen v historii/grafech?
- Budeme resit manualni ceny jako prvni fallback pro assety bez API provideru?
