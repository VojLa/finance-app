# Documentation migration plan

Type: reference
Status: proposed
Owns: pořadí, bezpečnost a akceptační kritéria dokumentační migrace
Code: všechny dokumentační kořeny a `scripts/docs`
Update when: změní se migrační pořadí nebo cílové kontroly

## Pořadí

1. Zavést šablony, registry typů, ID a cílové README rozcestníky.
2. Zkrátit L0/L1 mapy na routing a odstranit z nich doménový detail.
3. Vytvořit invariant catalog a přesunout přesná opakovaná pravidla.
4. Převést domény v pořadí identity → accounts → ledger/imports → market
   evidence → valuation → read models/history.
5. Vytvořit test taxonomy, quality gates a doménové test matrices.
6. Převést API, data, security a operations na vlastní typy dokumentů.
7. Přesunout milestone evidence z aktuální architektury do historie.
8. Sloučit číslované a sémantické paralelní cesty přes dočasné odkazy.
9. Doplnit `!user-docs` podle skutečně dostupných UI funkcí.
10. Zapnout CI pravidlo až po jeho splnění v celém kontrolovaném scope.

## Postup jednoho adresáře

1. Načíst README, všechny potomky a příchozí odkazy.
2. Porovnat obsah s runtime kódem, testy a generovanými inventáři.
3. Každý významový blok označit `current`, `planned`, `user`, `historical` nebo
   `generated`.
4. Určit jediného cílového vlastníka.
5. Přesunout informaci, nahradit kopii odkazem nebo odstranit duplikát.
6. Spustit targeted link, metadata a generated checks.
7. Starý soubor odstranit až po ověření všech příchozích odkazů.
8. Provést delta review pouze převáděného adresáře a sousedních routerů.

## První implementační řez

První řez ještě nepřepisuje domény. Vytvoří:

- šablony README, domain, module, flow, invariant, testing a runbook;
- registr typů a ID konvencí;
- cílové indexy `testing`, `data`, `security`, `operations` a invariants;
- checker, který nová pravidla nejdříve pouze reportuje;
- migrační inventář současných dokumentů s cílovým vlastníkem.

Druhý řez ověří systém na jedné doméně. Teprve po úpravě šablon podle reálné
zkušenosti se struktura zopakuje přes celý projekt.

## Akceptační kritéria

- Každý dokument odpovídá jednomu registrovanému typu.
- Každý adresář má krátký README a žádný dokument není osiřelý.
- Každá doména a autoritativní runtime modul jsou dohledatelné z L1 mapy.
- Každá kritická invarianta má jedno znění, enforcement point a test evidence.
- Každá testovací vrstva má účel, příkaz, prerequisites a CI vlastníka.
- Úplné seznamy rout, modelů, modulů, souborů a testů jsou pouze generované.
- Aktuální docs neobsahují future scope ani milestone auditní deník.
- Ruční soubory splňují měkké délkové limity nebo mají zdůvodněnou výjimku.
- Checker ověřuje links, README, length, metadata, freshness, orphan docs a
  odkazy na existující invarianty/testy.
- DOC IMPACT aktualizuje pouze skutečné vlastníky dotčených informací.
