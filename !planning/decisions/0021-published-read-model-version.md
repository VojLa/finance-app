# ADR 0021 - Atomická verze publikovaných read modelů

Status: Accepted
Date: 2026-09-02
Decision owners: finance-app owner

## Rozhodnutí

Každý uživatel má jeden řádek `UserReadModelPublication`. Obsahuje náhodný
neprůhledný token, poslední publikovaný `DailySnapshotBaseline`, seznam
dotčených oblastí a čas publikace; neobsahuje žádnou finanční hodnotu.

Při vytvoření nebo opravě publikovaného baseline se token zapisuje ve stejné
databázové transakci. Čtenář se nejprve autentizuje a pak může přes
`GET /api/v1/read-model-version?after=…` získat pouze změněný token a oblasti.
Stejný token vrací `204 No Content`. Odpověď je vždy `Cache-Control: no-store`.

Browser drží token jen v paměti otevřené záložky. V aktivní záložce ho ověří
nejvýše jednou za deset minut a obnoví pouze aktuálně zobrazené Portfolio nebo
Dashboard. Token ani finanční data se neukládají do localStorage, sessionStorage
ani sdílené HTTP cache.

## Důsledky

Tato verze je publikační fence, nikoliv zdroj ocenění. Její čtení nedělá provider
I/O, rekonstrukci portfolia ani audit historie. Při výpadku refreshu zůstává
platný poslední publikovaný snapshot. Další oblasti a budoucí SSE/WebSocket mohou
rozšířit seznam scopes bez změny bezpečnostní hranice.
