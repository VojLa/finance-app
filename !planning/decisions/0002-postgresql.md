# ADR 0002 - PostgreSQL jako hlavni databaze

Status: Accepted
Date: 2026-07-16
Decision owners: VojLa
Supersedes: none
Superseded by: none

## Kontext

Finance App potrebuje konzistentni ulozeni transakci, ledger udalosti, importniho auditu, snapshotu, cen a uzivatelskych dat. Databaze musi podporovat transakce, integritni omezeni, historii, indexovani a spolehlive migrace.

## Rozhodnuti

`PostgreSQL` bude centralni persistence vrstva a hlavni databaze aplikace.

- canonical domenova data budou ulozena v relacnich tabulkach,
- integrita bude chranena constraints a transakcemi,
- odvozene read modely a snapshoty zustanou sekundarni a rebuildovatelne,
- schema zmeny budou probihat pouze pres rizene migrace.

## Dusledky

Pozitivni:

- silna relacni a transakcni konzistence,
- vhodnost pro financni a ledger workload,
- kvalitni indexovani, agregace a historie,
- siroka provozni podpora.

Negativni:

- schema vyzaduje disciplinu,
- migrace a rollback musi byt navrzene pred nasazenim,
- velke analyticke workloady mohou pozdeji vyzadovat oddelenou read vrstvu.

## Zamitnute alternativy

- dokumentova databaze jako primarni source of truth,
- SQLite jako produkcni databaze,
- vice primarnich databazi pro jednotlive moduly od zacatku.

## Migracni nebo rollout plan

PostgreSQL zustane zachovan pri prechodu backendu z TypeScriptu do Pythonu. Meni se vlastnik schema migraci, nikoliv databazovy engine.