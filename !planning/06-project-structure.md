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
- `api/` ma byt tenka vrstva nad moduly
- `jobs/` orchestruje, ale nevlastni business pravidla
- `schemas/` drzi Pydantic kontrakty
- `db/` drzi DB integraci, ne domenove rozhodovani

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
