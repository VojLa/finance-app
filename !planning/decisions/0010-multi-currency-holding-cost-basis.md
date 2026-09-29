# ADR 0010 - Vice-menovy Holding cost basis

Status: Accepted
Date: 2026-08-10
Decision owners: vlastnik finance-app
Supersedes: none
Superseded by: none

## Kontext

Jeden listing je fungibilni pozice, ale jeho nakupy mohou byt vyporadane v
ruznych menach. Trading212 historie obsahuje soubezne otevrene nakupy stejneho
titulu v EUR i USD. `Holding.avgBuyPrice` a `Holding.currency` proto nemohou byt
jedinou autoritou skutecne porizovaci hodnoty.

## Rozhodnuti

Holding zachova jednu quantity a prumernou kotovanou execution cenu v mene
listingu. Skutecna porizovaci hodnota bude samostatny canonical breakdown
`mena -> castka`, odvozeny z fee-separated settlement principal jednotlivych
canonical movementu.

Nakup prida principal do odpovidajici meny. Castecny prodej snizi vsechny
otevrene cost komponenty stejnym pomerem zbyvajiciho mnozstvi k puvodnimu
mnozstvi. Plny prodej pozici i breakdown odstrani. Snapshot prevede kazdou
komponentu primo do output meny pomoci schvalene persisted FX evidence.
Snapshot item navic zachova `averageBuyPrice` a menu listingu. Tato quote
evidence nesmi byt zpetne odvozovana z vice-menoveho settlement breakdownu ani
z output-currency kompatibilnich poli, protoze je nutna pro presny forward
replay dalsich nakupu.

Settlement castka kazdeho nakupu je event-date provedena castka. Agregovany
otevreny breakdown se pri snapshotu prevadi primym snapshot-time kurzem; tento
ADR nezavadi lot/date cost ledger.

## Dusledky

- skutecna settlement evidence se neztrati ani neslouci bez FX dukazu;
- listing price a settlement cost maji explicitne rozdilnou semantiku;
- vice-menova pozice potrebuje breakdown i na snapshot item hranici;
- chybejici prime FX evidence zustava fail-closed;
- historicke single-currency Holdings lze bezeztratove backfillovat jednou
  komponentou `quantity * avgBuyPrice`.

## Zamitnute alternativy

- Vybrat prvni nebo posledni settlement menu: ztrata financni evidence.
- Predem prevest a ulozit jen jednu menu: ztrata puvodni settlement evidence.
- Pouzit jen raw listing cenu jako cost: ignoruje skutecny settlement a FX.
- Vytvorit vice Holdings pro jeden listing: rozbije fungibilni pozici a
  existujici account/listing invariant.
