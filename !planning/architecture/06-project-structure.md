# Project Structure

## Smysl dokumentu

Tento dokument popisuje cilovou strukturu repozitare a umisteni hlavni logiky. Cilem je rozhodnout, jak bude projekt fyzicky rozdelen pred tim, nez backend naroste do neprehledneho monolitu.

---

## Zakladni smer

- frontend zustava v `Next.js` a `TypeScript`
- hlavni backend logika se presouva do `Pythonu`
- vykonove tezke jadro muze pozdeji jit do `Rustu`
- dokumentace a planning zustavaji oddelene od implementace
- `Python API` je source of truth pro verejny API kontrakt
- frontendove TypeScript typy se generuji z OpenAPI, neudrzuji se rucne jako druha kopie

---

## Navrzena struktura

```text
frontend/
    app/
    components/
    lib/
    hooks/
    features/
    generated/
        api/

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
        tests/

contracts/
    openapi/
    json_schema/
    import_formats/

engine/
    rust/
        crates/
            ledger_replay/
            snapshot_builder/
            fx_math/

prisma/
    migrations/             # nemenny historicky SQL archiv; nikdy runtime

docs/
!planning/
```

---

## Pravidla struktury

- kazdy backend modul ma vlastni verejnou boundary
- `shared/` nesmi obsahovat business logiku
- `api/` je tenka transportni vrstva nad aplikacnimi use-cases
- `jobs/` orchestruje, ale nevlastni business pravidla
- `db/` drzi sdilenou DB infrastrukturu, ne domenove rozhodovani
- domenove a API schema patri primarne do modulu, ktery je vlastni
- globalni `schemas/` se nevytvari jako odkladiste nahodnych Pydantic modelu

### Pravidla pro kontrakty

- `Python API` je source of truth pro HTTP API kontrakt
- OpenAPI schema se generuje z FastAPI aplikace
- TypeScript klient a typy se generuji z OpenAPI do `frontend/generated/api/`
- generovane soubory se neupravuji rucne
- zmena API kontraktu musi projit contract testy a kontrolou dopadu na frontend
- `contracts/json_schema/` obsahuje pouze formaty, ktere nejsou prirozene vlastnene OpenAPI, například stabilni importni formaty
- `contracts/import_formats/` muze drzet verejne custom CSV nebo jine datove specifikace
- kontrakty nesmi obsahovat business logiku

---

## Modulovy template pro backend

Struktura modulu se ma prizpusobit jeho velikosti. Male moduly nemaji vytvaret prazdne vrstvy jen kvuli sablone. Vetsi moduly se ale nesmi sloucit do jednoho obriho `service.py`.

### Minimalni modul

```text
modules/
    notifications/
        service.py
        contracts.py
        repository.py
        tests/
```

### Vetsi domenovy modul

```text
modules/
    imports/
        api/
            routes.py
            schemas.py
        application/
            commands.py
            queries.py
            services.py
        domain/
            entities.py
            value_objects.py
            rules.py
            exceptions.py
        infrastructure/
            repository.py
            db_models.py
        contracts.py
        tests/
```

### Odpovednost vrstev

- `api/` prevadi HTTP vstup a vystup, ale nevlastni use-case logiku
- `application/` orchestruje use-cases a transakce mezi domenou a infrastrukturou
- `domain/` obsahuje entity, value objects, invarianty a cistou business logiku
- `infrastructure/` obsahuje persistence adaptery a integrace
- `contracts.py` definuje verejnou modulovou boundary pro ostatni backend moduly
- `api/schemas.py` obsahuje Pydantic HTTP schema konkretniho modulu
- `tests/` obsahuje testy daneho modulu; sdilene testovaci helpery patri do backendove testovaci infrastruktury

Modul se deli do podadresaru az ve chvili, kdy jednodussi struktura prestava byt prehledna. Cilem neni maximalni pocet vrstev, ale jasne vlastnictvi odpovednosti.

---

## Databazove schema a migrace

Cilovy stav:

- PostgreSQL je persistence vrstva
- SQLAlchemy modely popisuji Python persistence mapovani
- Alembic je jediny vlastnik databazovych migraci po dokonceni backendove migrace
- domenove entity nesmi byt automaticky totozne s ORM modely jen kvuli pohodli

Aktualni stav:

- SQLAlchemy mapuje kompletni fyzicke schema a Alembic je jeho jediny migracni vlastnik
- `prisma/migrations/` je nemenny historicky SQL archiv overovany agregatnim hashem
- Prisma runtime, `schema.prisma`, generator a migracni prikazy v repozitari nejsou
- nove tabulky nebo zmeny vznikaji pouze pres explicitni Alembic plan a revizni artefakt

---

## Migracni pravidlo

Po dokonceni runtime cutoveru:

- nova business logika patri do budouciho Python backend modulu, ne do novych `Next.js` route handleru
- `Next.js` route muze byt docasny adapter, ale ne dlouhodoby vlastnik logiky
- nove API kontrakty vznikaji v Python API a frontend z nich generuje klienta a TypeScript typy
- existujici TypeScript kontrakty se pri migraci postupne nahrazuji generovanymi kontrakty
- nesmi znovu vzniknout druhy ORM nebo migracni vlastnik stejnych tabulek
