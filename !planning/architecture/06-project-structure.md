# Project Structure

## Smysl dokumentu

Tento dokument popisuje cilovou strukturu repozitare a umisteni hlavni logiky. Cilem je rozhodnout, jak bude projekt fyzicky rozdelen pred tim, nez backend naroste do neprehledneho monolitu.

---

## Zakladni smer

- frontend zustava v `Next.js` a `TypeScript`
- hlavni backend logika se presouva do `Pythonu`
- vykonove tezke jadro muze pozdeji jit do `Rustu`
- dokumentace a planning zustavaji oddelene od implementace

---

## Navrzena struktura

```text
frontend/
    app/
    components/
    lib/
    hooks/
    features/

backend/
    app/
        api/
        modules/
            accounts/
            assets/
            imports/
            parsers/
            ledger/
            holdings/
            snapshots/
            prices_fx/
            read_models/
            notifications/
            audit/
            auth/
            reconciliation/
            corporate_actions/
        jobs/
        shared/
        config/
        db/
        schemas/
        tests/

shared_contracts/
    api/
    import_formats/
    read_models/

engine/
    rust/
        crates/
            ledger_replay/
            snapshot_builder/
            fx_math/

prisma/
docs/
!planning/
```

---

## Pravidla struktury

- kazdy backend modul ma mit vlastni service boundary
- `shared/` nesmi obsahovat business logiku
- `shared_contracts/` je samostatna vrstva vedle `frontend/` a `backend/`, ne uvnitr backend shared
- `api/` ma byt tenka vrstva nad moduly
- `jobs/` orchestruje, ale nevlastni business pravidla
- `schemas/` drzi Pydantic kontrakty
- `db/` drzi DB integraci, ne domenove rozhodovani

Pravidla pro `shared_contracts/`:

- drzi pouze stabilni kontrakty mezi frontendem a backendem
- nesmi drzet business logiku
- nesmi se zmenit nahodne bez kontroly dopadu na obe strany
- patri sem jen to, co opravdu potrebuji obe vrstvy

---

## Modulovy template pro backend

Kazdy modul by mel mit podobnou strukturu:

```text
modules/
    imports/
        service.py
        repository.py
        models.py
        contracts.py
        validators.py
        tests/
```

Minimalni pravidla:

- `service.py` drzi use-cases
- `repository.py` drzi persistence pristup
- `models.py` drzi internI domenove modely
- `contracts.py` drzi verejne modulove kontrakty
- `validators.py` drzi vstupni pravidla, pokud jsou potreba

---

## Migracni pravidlo

Dokud projekt bezi hybridne:

- nova business logika patri uz do budoucich backend modulu, ne do novych `Next.js` route handleru
- `Next.js` route muze byt docasny adapter, ale ne dlouhodoby vlastnik logiky
- pokud frontend a backend sdili DTO nebo read model shape, ma jit jejich stabilni definice do `shared_contracts/`, ne do nahodne utility slozky
