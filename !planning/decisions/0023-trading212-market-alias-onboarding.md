# ADR 0023 - Uzavrene market aliasy pro Trading 212

Status: Accepted
Date: 2026-09-04
Decision owners: vlastnik finance-app
Supersedes: none
Superseded by: none

## Kontext

Trading 212 export nese ticker, ISIN a menu, ale ne dostatecne presnou identitu
kotace pro konkretniho market providera. Canonical aktiva a broker listing proto
po importu existovaly bez provider aliasu a background finalizace nemohla ziskat
cenove podklady pro snapshoty.

## Rozhodnuti

Po uspesnem postingu Trading 212 davek finalizace automaticky doplni provider
aliasy z uzavreneho allowlistu. Vstup se shoduje soucasne podle ISIN, tickeru a
meny a musi odpovidat ulozenemu aktivu i broker listingu. Neznama nebo rozporna
identita skonci konfliktem bez odhadu a bez castecne publikace snapshotu.

Lokalni `local_free` rezim zapisuje Yahoo identity; kanonicky rezim zapisuje
Twelve Data identity vcetne MIC. Soucasny fixture allowlist je:

| Ticker | Yahoo | Twelve Data MIC |
| --- | --- | --- |
| AAPL | AAPL | XNAS |
| AMZN | AMZN | XNAS |
| BB3M | BB3M.L | XLON |
| BHP | BHP | XNYS |
| CCJ | CCJ | XNYS |
| EUNK | EUNK.DE | XETR |
| GOOG | GOOG | XNAS |
| IONQ | IONQ | XNYS |
| MO | MO | XNYS |
| MSFT | MSFT | XNAS |
| NIO | NIO | XNYS |
| NVDA | NVDA | XNAS |
| O | O | XNYS |
| P911 | P911.DE | XETR |
| QBTS | QBTS | XNYS |
| RGTI | RGTI | XNAS |
| SBUX | SBUX | XNAS |
| SHOP | SHOP | XNAS |
| TSLA | TSLA | XNAS |
| TSM | TSM | XNYS |
| VUAA | VUAA.MI | XMIL |
| VUSA | VUSA.L | XLON |
| VWCE | VWCE.DE | XETR |
| ZPRV | ZPRV.DE | XETR |

ISIN a mena jsou soucasti implementovaneho allowlistu, i kdyz tabulka zamerne
ukazuje jen provider routing. Alias writer zachovava svou idempotentni a
konfliktne uzavrenou transakcni hranici.

## Dusledky

- Opakovany import stejne identity alias pouze replayuje.
- Import noveho instrumentu vyzaduje vedome rozsireni allowlistu a test.
- Provider I/O zustava ve workeru; bezny read request aliasy ani ceny nedohledava.
- Stavajici canonical evidence a importni radky se nemeni ani nemazou.
