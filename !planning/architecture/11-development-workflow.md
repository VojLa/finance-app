# Development Workflow

## Smysl dokumentu

Tento dokument popisuje standardni cestu od napadu po release. Je to kazdodenni workflow pro vyvoj.

---

## Zakladni tok

```text
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
```

Ne kazda zmena potrebuje stejny rozsah formalniho planningu. Hloubka procesu se ridi dopadem zmeny.

---

## Klasifikace zmen

### Mala zmena

Samostatny planning dokument nebo ADR neni nutny, pokud zmena:

- nemeni verejny API nebo datovy kontrakt
- nemeni vlastnictvi dat ani source of truth
- nemeni modulovou hranici nebo smer zavislosti
- nemeni databazove schema nebo migracni ownership
- nemeni technologicke rozhodnuti
- neopravuje nejasne nebo sporni business pravidlo
- nema vyznamny bezpecnostni nebo provozni dopad

Priklady:

- lokalni oprava UI
- oprava preklepu
- refaktor uvnitr jednoho modulu bez zmeny chovani
- doplneni testu pro existujici pravidlo
- oprava chyby, jejiz spravne chovani je uz jasne definovane

Mala zmena stale vyzaduje odpovidajici testy a review.

### Vyznamna zmena

Planning nebo ADR je povinny, pokud zmena:

- meni verejny kontrakt
- meni vlastnika dat nebo source of truth
- pridava novou domenu nebo meni modulove hranice
- zavadi novou technologii nebo infrastrukturu
- meni databazove schema s dlouhodobym dopadem
- meni financni vypocet, invariant nebo interpretaci dat
- meni auth, autorizaci, audit nebo bezpecnostni hranici
- zavadi novy provozni mechanismus, ktery ovlivni recovery nebo spolehlivost

Pokud si vyvojar neni jist klasifikaci, zmena se povazuje za vyznamnou, dokud se nerozhodne jinak.

---

## Pravidla jednotlivych kroku

### 1. Idea

- vznikne napad, problem nebo pozadavek
- nejdriv se urci, jestli jde o feature, technicky dluh, parser, bug nebo architektonicke rozhodnuti
- idea se zapise do aktualniho scope, issue nebo backlogu podle priority

### 2. Planning

- idea se porovna s roadmapou, scope a business prioritami
- rozhodne se, jestli patri do aktualni faze nebo backlogu
- u male zmeny muze byt planning omezen na jasny issue nebo PR popis
- u vyznamne zmeny musi byt znamy owner dat, dopad na moduly, kontrakty a testovaci strategie

### 3. Decision

- pokud ma vec dlouhodoby dopad, vznikne nebo se upravi ADR
- pokud meni modulove hranice, musi byt zapsana v architecture dokumentech
- ADR se nevytvari pro bezne implementacni detaily bez dlouhodobeho dopadu

### 4. Implementation

- implementuje se az po dostatecnem uzavreni potrebne planning a decision casti
- kod musi respektovat moduly, source of truth a coding standards
- generovane soubory se neupravuji rucne
- docasne adaptery a migracni zkratky musi byt explicitne oznacene a mit plan odstraneni

### 5. Tests

- nova logika bez odpovidajicich testu neni hotova
- parser a vypocetni opravy musi mit regression ochranu
- zmena API kontraktu musi mit contract nebo integration test
- migrace databaze musi byt overitelna dopredu i z pohledu rollback nebo recovery postupu

### 6. Review

- kontroluje se spravnost, scope fit, modulove hranice, bezpecnost a testy
- u vyznamne zmeny se kontroluje soulad s ADR a architecture dokumenty
- pokud chybi nutne rozhodnuti, review vraci zmenu do planning nebo decision kroku

### 7. Merge

- merge prichazi az po review a uspesnych testech
- branch musi byt v souladu s aktualnim target branchem
- PR musi jasne popsat dopad, zpusob overeni a pripadne navazujici praci

### 8. Release

- release se ridi podle release strategy a aktualni faze produktu
- zmena, ktera vyzaduje migraci, feature flag nebo postupny rollout, musi mit tento postup pripraveny pred releasem

---

## Definition of Done pro zmenu

Zmena je hotova, kdyz:

- implementace odpovida schvalenemu scope
- vlastnictvi dat a modulove hranice zustaly jasne
- testy odpovidaji riziku zmeny a prochazeji
- dokumentace a ADR jsou aktualizovane, pokud je zmena ovlivnila
- nejsou ponechane nezdokumentovane docasne zkratky
- PR popisuje, jak byla zmena overena

---

## Zakladni pravidlo

Pokud neni jasne, kam vec patri nebo podle jakeho pravidla se ma udelat, workflow se vraci zpet do planning nebo decision vrstvy. Proces ale nema vytvaret administrativu pro male zmeny, ktere nemeni kontrakty, vlastnictvi dat ani architekturu.
