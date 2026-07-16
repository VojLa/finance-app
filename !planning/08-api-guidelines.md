# API Guidelines

## Smysl dokumentu

Tento dokument sjednocuje pravidla pro API navrh, aby backend po case nevypadal jako sbirka nesourodých endpointu.

---

## Zakladni pravidla

- API je resource-oriented, ale use-case driven tam, kde to dava vetsi smysl
- response shape musi byt konzistentni
- chyby musi byt strukturovane
- autentizace a autorizace musi byt jednotna

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

## Versioning

- nepridavat verze zbytecne brzy
- ale drzet kontrakty tak, aby byly rozsiritelne
- pokud dojde ke skutecnemu breaking change, verze musi byt explicitni

---

## Authentication

- auth boundary musi byt jednotna mezi frontendem a backendem
- endpoint nesmi byt verejnejsi nez jeho data
- account-level data se vzdy autorizuji pres vztah user -> account

---

## Special rules for this product

- parse warnings a import issues se vraceji strukturovane, ne jako volny text
- partial data stav musi byt rozpoznatelny
- portfolio a dashboard nesmi vracet stejnou metriku ruznou logikou
