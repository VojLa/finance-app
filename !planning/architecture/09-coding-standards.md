# Coding Standards

## Smysl dokumentu

Tento dokument nastavuje vyvojarske standardy pro backend, frontend i testy. Cilem je, aby kod zustal konzistentni i po rustu tymu.

---

## Obecna pravidla

- cistota a srozumitelnost maji prednost pred trikem
- business logika nesmi byt schovana v utility vrstve
- novy kod ma respektovat modulove hranice
- komentare jen tam, kde realne pomahaji

---

## Naming conventions

- moduly pojmenovavat podle domen, ne podle technicke implementace
- funkce pojmenovavat podle use-case, ne podle detailu implementace
- vyhybat se zkratkam bez jasneho vyznamu

### Folder naming

- slozky pojmenovavat konzistentne malymi pismeny
- backend moduly pojmenovavat podle domen, napr. `imports`, `ledger`, `snapshots`

### File naming

- soubory pojmenovavat predvidatelne podle role, napr. `service.py`, `repository.py`, `contracts.py`
- nepojmenovavat soubory podle docasnych implementacnich detailu

### Class naming

- tridy pojmenovavat podle domenoveho vyznamu
- vyhybat se generickym nazvum jako `Manager`, `Helper`, `Processor`, pokud nejde o opravdu technickou roli

### Method naming

- metody pojmenovavat podle vysledku nebo use-case
- preferovat `create_import_batch`, `rebuild_snapshots`, `get_portfolio_read_model` pred neurcitymi nazvy

---

## Modulova struktura

- API vrstva ma byt tenka
- orchestrace patri do service vrstvy
- persistence patri do repository vrstvy
- DTO a kontrakty maji byt explicitni

### Import rules

- importovat jen to, co modul skutecne potrebuje
- omezovat cyclic dependencies
- frontend nesmi importovat backend business logiku

### Dependency direction

- UI zavisi na kontraktech, ne na backend implementaci
- API zavisi na modulech
- read modely zavisi na canonical datech, ne obracene
- shared utility nesmi zavadet zpetnou business zavislost

---

## Dependency injection

- zavislosti maji byt explicitni
- modul nema sahat na globalni stav, pokud to neni nutne
- side effects nesmi byt skryte

---

## Logging

- logovat dulezite workflow body
- logovat identifikatory batchu, jobu a accountu
- nelogovat zbytecny sum ani citliva data bez duvodu

---

## Error handling

- nepohlcovat chyby potichu
- vracet stabilni error codes
- odlisovat user-facing a internal diagnostiku

---

## Testy

- novy business use-case ma prijit s testem
- parser nebo vypocetni oprava bez regression testu neni uzavrena prace

---

## Commit messages

- psat vecne a konkretne
- popsat zmenu z pohledu vysledku, ne jen souboru

Priklad:

- `Add custom CSV import contract for unsupported institutions`
- `Fix event-date FX handling in account snapshots`
