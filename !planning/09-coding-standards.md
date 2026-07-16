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

---

## Modulova struktura

- API vrstva ma byt tenka
- orchestrace patri do service vrstvy
- persistence patri do repository vrstvy
- DTO a kontrakty maji byt explicitni

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
