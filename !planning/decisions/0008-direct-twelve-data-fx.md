# ADR 0008 - Prime devizove kurzy z Twelve Data

Status: Accepted
Date: 2026-08-10
Decision owners: vlastnik finance-app
Supersedes: none
Superseded by: none

## Kontext

Puvodni produkcni adapter CNB poskytoval jen kurz cizi meny vuci CZK. Prevod
mezi dvema cizimi menami proto skladal dva fyzicke kurzy pres CZK. Vedle nej
existovaly historicke Yahoo radky a starsi TypeScript zapis, takze stejna mena a
datum mohly mit vice zdroju. To neni vhodne pro cil, ve kterem je jeden
auditovatelny kurz primo pro pozadovanou dvojici.

## Rozhodnuti

Jedinym registrovanym produkcnim FX providerem je Twelve Data. Kazdy pozadavek
obsahuje presnou dvojici `FROM/TO` a datum `through`; provider vola denni
`/time_series` pro tuto dvojici a vrati nejnovejsi nebudouci bod. Aplikace kurz
neobraci, nesklada pres CZK, neprepina zdroj a nevytvari synteticky radek.

API klic je pouze serverovy secret v Authorization headeru. Chybejici klic,
quota, HTTP chyba, necekane schema, jina orientace, budouci/stary bod nebo
nepresna hodnota uzavrou cely refresh bez castecneho zapisu.

Hodnoty enumu `cnb` a `yahoo_finance` a stare radky zustavaji citelne kvuli
historickemu auditu. Produkci je logicky karantenuje source-aware registry a
selector, ktery akceptuje jen `twelve_data`.

## Dusledky

- EUR/USD a dalsi cizi dvojice pouzivaji jeden fyzicky prime pozorovany kurz.
- Snapshot-time a event-time semantika zustava oddelena.
- Stejna fyzicka identita se pres UUIDv5 presne replayuje; rozdilna hodnota je
  konflikt.
- Stare snapshoty s pivot lineage se nemeni a zustavaji citelne. Nove snapshoty
  zapisuji pouze roli `direct`.
- Technicke nasazeni do produkce vyzaduje aktivni Twelve Data API klic a overena
  licencni prava pro zamyslene internal non-display pouziti.

## Zamitnute alternativy

- CNB pivot: nema prime foreign-to-foreign pozorovani.
- Invertovani nebo triangulace v aplikaci: vytvarely by odvozeny kurz s jinou
  lineage nez provider.
- Automaticky fallback mezi zdroji: mohl by zmenit vysledek bez zmeny kontraktu.
- Smazani vsech starych Yahoo/CNB radku: znicilo by auditni a snapshot lineage.

## Migracni nebo rollout plan

1. Alembic prida `twelve_data` do `ExchangeRateSource`.
2. Produkci se zaregistruje jen Twelve Data FX adapter a direct-pair planner.
3. Read-only audit vypise zdroje, kolize, neplatne radky a snapshoty zavisle na
   legacy rate ID.
4. Pred jakymkoli operatornim cistenim se zalohuji tabulky market evidence a
   snapshotu. Historicke snapshoty se neprepisuji; novy refresh vytvori nove
   prime evidence a snapshoty.
5. CNB runtime a TS Yahoo/rates runtime se odstrani. Historicke enum identity
   zustavaji zachovane.
