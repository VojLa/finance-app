# ADR 0004 - Oddeleni read modelu od canonical historie

Status: Accepted
Date: 2026-07-16
Decision owners: VojLa
Supersedes: none
Superseded by: none

## Kontext

Canonical historie musi presne zachytit, co se stalo. Frontend ale potrebuje rychle a ergonomicke pohledy pro portfolio, dashboard, grafy a reporting. Pokud by se prezentacni agregace staly primarni historii, vznikla by nekonzistence a obtizne opravitelna data.

## Rozhodnuti

Portfolio, dashboard, reporting a analyticke odpovedi budou read modely postavene nad canonical domenovymi daty.

- ledger a dalsi canonical domeny vlastni historickou pravdu,
- holdings a snapshots jsou odvozene a rebuildovatelne vrstvy,
- read modely nevlastni primarni business historii,
- stejna metrika musi ve vsech pohledech vychazet ze stejne definice.

## Dusledky

Pozitivni:

- oddeleni historie od prezentace,
- rychlejsi a stabilnejsi API odpovedi,
- moznost cache a materializace,
- oprava odvozenych dat rebuildem z canonical zdroju.

Negativni:

- vice vrstev a synchronizacnich workflow,
- potreba validovat shodu canonical a odvozenych dat,
- eventualni konzistence u nekterych asynchronnich vypoctu.

## Zamitnute alternativy

- pocitat kazdy dashboard request plnym replayem,
- ukladat dashboard agregace jako jedinou historii,
- mit rozdilnou logiku financnich metrik pro kazdy endpoint.

## Migracni nebo rollout plan

Nejprve se zavede minimalni end-to-end tok `ledger -> holdings -> snapshots -> read models`. Optimalizace a cache se pridaji az po overeni spravnosti.
