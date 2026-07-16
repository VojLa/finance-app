# Testing Strategy

## Smysl dokumentu

Tento dokument popisuje, jak budeme testovat aplikaci tak, aby data zustala duveryhodna i pri rustu scope a po migraci backendu do Pythonu.

---

## Testovaci vrstvy

### Unit testy

Pouziti:

- parser transform logika
- mensi vypocetni funkce
- validator pravidla
- FX a cost basis helpery

### Integracni testy

Pouziti:

- backend moduly nad DB
- import workflow
- snapshot build
- portfolio a dashboard read modely

### Fixture testy

Pouziti:

- realne exporty bank, brokeru a smenaren
- parser parity
- regression ochrana proti rozbiti importu

### Snapshot a ledger parity testy

Pouziti:

- porovnani canonical historie a odvozenych vysledku
- kontrola, ze holdings a snapshots odpovidaji ledgeru

### End-to-end smoke testy

Pouziti:

- hlavni user flow
- login -> account -> import -> portfolio -> dashboard

---

## Povinne oblasti testovani

- parsery
- import idempotence
- multi-file import
- append-only ledger opravy
- holdings po castecnych a plnych prodejich
- FX pravidla podle data udalosti
- snapshot rebuild a live continuation
- portfolio a dashboard konzistence
- reconciliation drift detection

---

## Fixture pravidla

- kazda podporovana instituce ma mit fixture
- fixture musi reprezentovat realny export
- fixture se nesmi "cistit" tak, ze zmizi edge case
- unsupported rows musi byt testovane jako parse issues

---

## Testovaci priorita

1. canonical data
2. odvozene vypocty
3. API kontrakty
4. UI smoke flow

Pokud je konflikt mezi mnozstvim testu a kvalitou testu, priorita je pokryt canonical a vypocetni vrstvy.
