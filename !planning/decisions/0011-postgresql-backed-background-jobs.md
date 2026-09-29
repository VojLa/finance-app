# ADR 0011 - PostgreSQL-backed background joby

Status: Accepted
Date: 2026-08-10
Decision owners: vlastnik finance-app
Supersedes: none
Superseded by: none

## Kontext

Import, Holding rebuild, provider evidence a snapshot mohou trvat dele nez
zivot browser requestu. Pro verzi R12 neni potreba distribuovana fronta, ale
operace musi prezit zavreni stranky a restart API a musi byt dohledatelna,
autorizovana, idempotentni a opakovatelna.

## Rozhodnuti

PostgreSQL bude zdrojem pravdy pro job lifecycle. Python worker claimuje
pripraveny job pomoci `FOR UPDATE SKIP LOCKED`, vlastni casove omezeny lease a
zapisuje strukturovany progress. Expirovany lease je znovu claimovatelny.
Business kroky zustavaji idempotentni a jejich canonical transakce nejsou
slouceny s dlouhou worker transakci.

Start endpoint vraci `202 Accepted`. Status a retry endpointy vzdy znovu overi
identitu a account boundary. Job payload neobsahuje raw financni obsah ani
secrets. Verejna chyba je stabilni safe code/message; interni traceback se do
jobu neuklada.

## Dusledky

- browser ani Next.js request nemusi zustat otevreny;
- restart procesu neztrati prijatou praci;
- vice API instanci muze bezpecne sdilet jednu frontu;
- R12 nepotrebuje Redis, Celery ani novou provozni sluzbu;
- polling zobrazuje progress, ale financni read model publikuje jen atomicky
  dokonceny snapshot.

## Zamitnute alternativy

- FastAPI `BackgroundTasks` nebo hole `asyncio.create_task`: prace se ztrati pri
  restartu a nema trvaly lifecycle.
- Pouhe prodlouzeni HTTP timeoutu: browser zustava vlastnikem dlouhe operace.
- Redis/Celery v R12: neprimerena nova infrastruktura pro soucasny rozsah.
