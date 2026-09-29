# ADR 0017 - Kreditní karta jako znaménkový účetní zůstatek

Status: Accepted
Date: 2026-08-31
Decision owners: finance-app owner
Supersedes: none
Superseded by: none

## Kontext

Importované pohyby kreditní karty jsou úplná účetní historie od nulového
počátku. Vyžadovat vedle nich ručně zadaný aktuální dluh blokuje publikaci,
a kreditní limit není ani majetek, ani důkaz skutečného dluhu.

## Rozhodnutí

Kreditní karta se ve valuaci, snapshotu a Net Worth chová jako účet se
znaménkovým cash zůstatkem odvozeným z canonical transakcí. Nákup vytváří
záporný zůstatek, splátka jej zvyšuje. Kreditní limit zůstává atributem účtu,
ale nevstupuje do zůstatku, snapshotu ani Net Worth. Pro kreditní kartu se
nevyžaduje `LiabilityBalance`; tato explicitní evidence zůstává nutná pro
úvěr a hypotéku.

## Důsledky

- import kreditní karty může po zaúčtování transakcí dokončit bez ručního
  zůstatku závazku;
- záporný zůstatek sníží Net Worth přes zápornou cash složku;
- případný kladný zůstatek karty se projeví jako kladný účetní zůstatek;
- starší snapshoty založené na `LiabilityBalance` pro kreditní kartu se
  nepřepisují; nově přepočtené snapshoty používají tuto semantiku.

## Zamítnuté alternativy

- Použít kreditní limit jako počáteční hotovost nebo dluh: zkreslilo by to
  Net Worth.
- Vyžadovat ruční aktuální dluh: je nadbytečné, pokud import obsahuje úplnou
  historii pohybů od nuly.
