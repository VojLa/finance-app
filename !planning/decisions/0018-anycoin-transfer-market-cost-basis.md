# ADR 0018 - Anycoin prevody s trzni porizovaci cenou

Status: Accepted
Date: 2026-08-31
Decision owners: vlastnik finance-app
Supersedes: none
Superseded by: none

## Kontext

Anycoin BTC vklady a vybery jsou canonical `asset_transfer` udalosti. Export
neobsahuje puvodni nakladovou bazi ani settlement castku, proto Holding dosud
spravne oznacoval basis jako nedostupnou.

Vlastnik aplikace rozhodl, ze pro tyto prevody bude ekonomickou cenou trzni cena
BTC v case udalosti; pokud minutova evidence neni pravdive dostupna, pouzije se
historicka denni cena daneho dne.

## Rozhodnuti

Pouze pro presne rozpoznany Anycoin BTC `asset_transfer` bez dodane ceny se
nemeni canonical `InvestmentMovement`. Misto toho se vytvori append-only
`InvestmentMovementValuationEvidence`, ktera k nemennemu movementu pripoji
overenou historickou cenu a `quantity * price` v mene Anycoin listingu. Evidence
obsahuje canonical revision, deterministicky input fingerprint, citovanou price
snapshot a pripadnou FX evidenci vcetne zkopirovanych hodnot. Zdroj ceny
odpovida aktivni source policy a evidence musi byt persistovana pred projekci
Holding basis.

Prvni evidence pohybu ma vlastni `revision = 1`; `canonicalRevision` je skutecna
revision odpovidajici canonical investment eventu a je soucasti fingerprintu.
Zkopirovane hodnoty se pri kazdem cteni overi proti citovanym nemennym radkum
`PriceSnapshot` a `ExchangeRate`. `selectionInterval` uchovava, zda uspesna
akvizicni vetev pouzila explicitni 30minutovy interval, nebo denni fallback.

Vyber ceny je as-of k minute udalosti; denni cenova observation je pripustny
fallback jen pokud patri do stejneho kalendarniho dne UTC. Pozdejsi, aktualni,
pivotovana nebo providerem neoverena cena se nepouzije. Pro Anycoin je identita
uzamcena na BTC-USD z Yahoo Finance a primy USD-CZK kurz ze stejneho zdroje.
Protoze fiat FX trh o vikendu nepublikuje stejnodenni bod, pouzije se posledni
dostupny primy as-of kurz, maximalne sedm dni stary; budouci kurz je zakazan.
Pokud nelze ziskat vyhovujici cenu nebo FX, finalizace selze bez castecneho
doplneni basis.

Stejna cena se zapisuje pro prichozi i odchozi transfer. Prichozi transfer ji
prida do Holding basis; odchozi transfer nese svou ocenovaci evidenci a snizi
otevrenou basis dosavadni pozice pomerne podle ADR 0010. Toto rozhodnuti samo
nezavadi danovy realized P/L model.

## Dusledky

- cost basis Anycoin BTC je dopoctena z event-date evidence, nikdy z aktualni
  ceny;
- replay musi byt idempotentni: shodny movement, canonical revision a input
  fingerprint znovu pouziji stejnou evidence; rozpor selze;
- zapis evidence a rebuild Holdingu probiha v jedne canonical-lock-protected
  transakci; market observations mohou byt bezpecne ulozeny pred ni;
- uz existujici Anycoin pohyby lze doplnit explicitnim canonical repair workflow
  stejnymi pravidly, ktery prida novou evidence overlay a nemeni movement;
- zmena plati jen pro uzce definovany Anycoin BTC import, nikoli pro obecne
  kryptomenove prevody.

## Zamitnute alternativy

- Nulova porizovaci cena: zfalšovala by P/L.
- Aktualni kurz: nebyl by cenou v den transakce.
- Odvozeni ve frontendu nebo jen ve snapshotu: vytvorilo by jinou historii nez
  canonical Holding projection.
- Obecny symbolovy fallback: porusil by explicitni identity hranici ADR 0013.
