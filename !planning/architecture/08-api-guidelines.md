# API Guidelines

## Smysl dokumentu

Tento dokument sjednocuje pravidla pro API navrh, aby backend po case nevypadal jako sbirka nesourodých endpointu.

---

## Zakladni pravidla

- API je resource-oriented, ale use-case driven tam, kde to dava vetsi smysl
- response shape musi byt konzistentni
- chyby musi byt strukturovane
- autentizace a autorizace musi byt jednotna
- `Python API` je source of truth pro HTTP API kontrakt
- frontendove typy a klient se generuji z OpenAPI, neudrzuji se rucne jako druha definice

---

## Vlastnictvi API kontraktu

- FastAPI endpointy a jejich Pydantic schema vlastni API kontrakt
- OpenAPI schema se generuje automaticky z Python API
- generovane OpenAPI schema se validuje v CI
- TypeScript klient a typy se generuji z OpenAPI do frontendove generovane vrstvy
- generovane TypeScript soubory se neupravuji rucne
- breaking change musi byt vedomy, zdokumentovany a pokryty contract testy
- stabilni datove formaty mimo HTTP API, například custom CSV kontrakt, mohou byt definovany samostatnym JSON Schema
- business pravidla nesmi byt vlozena do generacni vrstvy ani do schema souboru

---

## URL naming

- pouzivat podstatna jmena, ne nahodne slovesa
- priklady:
  - `/accounts`
  - `/imports/batches`
  - `/portfolio`
  - `/dashboard`
  - `/snapshots/rebuild`

---

## Response format

Preferovany shape:

```json
{
  "data": {},
  "meta": {},
  "issues": []
}
```

Pravidla:

- `data` je hlavni payload
- `meta` drzi paging, source, timestamps nebo quality info
- `issues` drzi warningy, parse issues nebo partial-data stavy

---

## Error format

Preferovany shape:

```json
{
  "error": {
    "code": "import_failed",
    "message": "Import batch failed.",
    "details": {}
  }
}
```

Pravidla:

- `code` je stabilni strojove citelny identifikator
- `message` je user-facing nebo developer-facing vysvetleni
- `details` drzi dalsi strukturovane informace

---

## Pagination

- vsude, kde muze seznam rust, musi byt predem rozhodnute strankovani
- preferovat cursor-based pagination pro velke a historicke seznamy
- offset pagination pouze pro male administrativni seznamy

---

## Filtering

- filtry musi byt explicitni a pojmenovane konzistentne
- account-level endpointy musi umet filtrovat aspon podle `accountId`, pokud to dava smysl
- datumove filtry maji mit predvidatelne nazvy jako `from`, `to`, `dateFrom`, `dateTo`

---

## Sorting

- trideni musi byt explicitni, ne skryte
- vychozi sort ma byt zdokumentovany
- pokud endpoint podporuje vice sortu, kontrakt musi rict, ktere hodnoty jsou povolene

---

## Versioning

- nepridavat verze zbytecne brzy
- ale drzet kontrakty tak, aby byly rozsiritelne
- pokud dojde ke skutecnemu breaking change, verze musi byt explicitni
- prejmenovani nebo odstraneni pole je breaking change
- pridani povinneho request pole je breaking change
- pridani volitelneho response pole nema byt breaking change, pokud klienti ignoruji nezname hodnoty

---

## Idempotency

- endpointy pro import start, rebuild a jine opakovatelne joby musi mit jasne idempotentni chovani
- pokud stejna operace prijde vicekrat, backend nesmi vytvorit duplicity jen kvuli opakovani requestu
- kde to dava smysl, ma existovat idempotency key nebo ekvivalentni ochrana

---

## Authentication

- auth boundary musi byt jednotna mezi frontendem a backendem
- endpoint nesmi byt verejnejsi nez jeho data
- account-level data se vzdy autorizuji pres vztah user -> account

---

## Async jobs and long-running operations

Pro tento produkt jsou importy, snapshot rebuildy a reconciliation casto asynchronni. API pro tyto use-cases musi mit jednotna pravidla.

### Start operation response

Endpoint, ktery spousti dlouhou operaci, ma vratit strukturovany stav:

```json
{
  "data": {
    "jobId": "job_123",
    "status": "queued"
  },
  "meta": {
    "kind": "import_batch"
  },
  "issues": []
}
```

### Status response

Status endpoint ma vracet aspon:

- `jobId`
- `status`
- `createdAt`
- `updatedAt`
- `kind`
- `progress`, pokud je dostupny
- `result`, pokud je hotovo
- `error`, pokud operace selhala

Preferovane stavy:

- `queued`
- `running`
- `completed`
- `failed`
- `cancelled`, pokud bude podporovano

### Polling rules

- polling endpoint musi byt idempotentni
- klient musi umet rozpoznat, zda jde o finalni nebo nefinalni stav
- partial progress nesmi byt schovany do volneho textu

### Partial and warning states

- `issues` zustavaji i u uspesne dokoncene operace
- warning stav se nesmi modelovat jako hard failure
- import parse issues musi byt vratitelne i kdyz batch celkove uspel

---

## Contract testing

CI musi overovat minimalne:

- OpenAPI schema lze uspesne vygenerovat
- generovany TypeScript klient odpovida aktualnimu OpenAPI schematu
- zmena kontraktu nezanechala necommitnute generovane rozdily, pokud jsou generovane soubory verzovane
- hlavni frontend-backend workflow prochazi contract nebo integration testem
- breaking zmena ma odpovidajici rozhodnuti, migracni plan nebo explicitni verzi

---

## Special rules for this product

- parse warnings a import issues se vraceji strukturovane, ne jako volny text
- partial data stav musi byt rozpoznatelny
- portfolio a dashboard nesmi vracet stejnou metriku ruznou logikou
- async import, snapshot a reconciliation workflow musi mit jednotny status kontrakt
