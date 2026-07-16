# Development Workflow

## Smysl dokumentu

Tento dokument popisuje standardni cestu od napadu po release. Je to kazdodenni workflow pro vyvoj.

---

## Zakladni tok

Idea

↓

Planning

↓

Decision

↓

Implementation

↓

Tests

↓

Review

↓

Merge

↓

Release

---

## Pravidla jednotlivych kroku

### 1. Idea

- vznikne napad, problem nebo pozadavek
- jeste se neimplementuje
- nejdriv se urci, jestli jde o feature, technicky dluh, parser nebo architektonicke rozhodnuti

### 2. Planning

- idea se porovna s roadmapou, scope a business prioritami
- rozhodne se, jestli patri do aktualni faze nebo backlogu

### 3. Decision

- pokud ma vec dlouhodoby dopad, vznikne nebo se upravi ADR
- pokud meni modulove hranice, musi byt zapsana v architecture dokumentech

### 4. Implementation

- implementuje se az po uzavreni planning a decision casti
- kod musi respektovat moduly, source of truth a coding standards

### 5. Tests

- nova logika bez odpovidajicich testu neni hotova
- parser a vypocetni opravy musi mit regression ochranu

### 6. Review

- kontroluje se spravnost, scope fit, modulove hranice a testy
- review neresi zpetne planning, pokud planning chybi, vraci se krok zpet

### 7. Merge

- merge prichazi az po review a testech

### 8. Release

- release se ridi podle release strategy a aktualni faze produktu

---

## Zakladni pravidlo

Pokud neni jasne, kam vec patri nebo podle jakeho pravidla se ma udelat, workflow se vraci zpet do planning nebo decision vrstvy. Nemelo by se improvizovat az v implementaci.
