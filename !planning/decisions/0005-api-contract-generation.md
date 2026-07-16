# ADR 0005 - Generovani API kontraktu z OpenAPI

Status: Accepted
Date: 2026-07-16
Decision owners: VojLa
Supersedes: none
Superseded by: none

## Kontext

Frontend v TypeScriptu a backend v Pythonu potrebuji sdilet stabilni API kontrakt. Rucni udrzovani stejnych DTO ve dvou jazycich by vedlo k driftu, rozdilnym typum a chybam zjistenym az za behu.

## Rozhodnuti

Python API bude source of truth pro HTTP kontrakt.

- FastAPI bude generovat OpenAPI schema,
- TypeScript typy a API klient se budou generovat z OpenAPI,
- JSON Schema muze byt pouzito pro dalsi stabilni datove kontrakty,
- generovane soubory se nebudou rucne upravovat,
- breaking zmena kontraktu musi byt explicitni a otestovana.

## Dusledky

Pozitivni:

- jeden source of truth,
- mensi riziko driftu mezi frontendem a backendem,
- automatizovatelne contract testy,
- jednodussi budouci klienti.

Negativni:

- zavislost na generatoru a jeho konfiguraci,
- potreba hlidat kompatibilitu generovanych vystupu,
- nektere domenove kontrakty mohou vyzadovat samostatne schema mimo HTTP API.

## Zamitnute alternativy

- rucne duplikovane Python a TypeScript typy,
- TypeScript jako source of truth pro Python backend,
- sdileni runtime knihovny mezi dvema ruznymi jazyky.

## Migracni nebo rollout plan

1. Stabilizovat prvni FastAPI endpointy.
2. Exportovat OpenAPI schema v CI.
3. Generovat TypeScript klienta a typy.
4. Pridat kontrolu, ze generovane kontrakty nejsou zastarale.