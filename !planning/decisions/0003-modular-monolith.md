# ADR 0003 - Modularni monolit jako vychozi architektura

Status: Accepted
Date: 2026-07-16
Decision owners: VojLa
Supersedes: none
Superseded by: none

## Kontext

Aplikace bude obsahovat vice domen, ale v prvnich fazich ji vyviji maly tym. Mikrosluzby by prinesly sitovou, provozni a datovou slozitost driv, nez existuje meritelna potreba samostatneho skalovani.

## Rozhodnuti

Python backend bude vytvoren jako modularni monolit.

- domeny budou mit explicitni hranice, vlastnictvi dat a verejne kontrakty,
- moduly nesmi obchazet ostatni moduly nahodnymi primymi zapisy,
- nasazeni zustane zpočatku jednotne,
- oddeleni modulu do samostatne sluzby bude mozne pouze na zaklade realne potreby.

## Dusledky

Pozitivni:

- jednodussi lokalni vyvoj, testovani a nasazeni,
- rychlejsi zmeny hranic v ranem vyvoji,
- domenove oddeleni bez distribuovane slozitosti,
- vhodne pro maly a postupne rostouci tym.

Negativni:

- hranice nejsou vynucene siti,
- spatna disciplina muze vest k provazanemu monolitu,
- nektere moduly mohou pozdeji vyzadovat extrakci.

## Zamitnute alternativy

- mikrosluzby od prvni verze,
- jedna neclenena backendova vrstva,
- samostatna sluzba pro kazdy parser nebo read model.

## Migracni nebo rollout plan

Kazdy modul zacne s jasnym service boundary a vlastnictvim dat. Pripadna extrakce do samostatne sluzby bude nove ADR.