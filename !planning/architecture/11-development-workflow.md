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
- pracuje s novym typem citlivych dat, souboru, externi integrace nebo secretu
- zavadi novy provozni mechanismus, ktery ovlivni recovery nebo spolehlivost

Pokud si vyvojar neni jist klasifikaci, zmena se povazuje za vyznamnou, dokud se nerozhodne jinak.

---

## Bezpecnostni klasifikace

Kazda zmena se pri planningu posoudi podle `10-security-strategy.md`.

Bezpecnostni posouzeni je povinne, pokud zmena:

- cte nebo zapisuje user-specific financni data,
- pridava endpoint, background job, import nebo export,
- meni session, cookies, tokeny, role nebo opravneni,
- prijima soubor nebo data z externiho zdroje,
- meni logovani, audit, zalohy nebo retention,
- pridava zavislost, secret, provider nebo produkcni pristup,
- meni trust boundary nebo zvetsuje verejny attack surface.

Minimalni vystup posouzeni:

- co je chranene aktivum,
- kdo smi operaci provest,
- jak se overuje account isolation,
- jak se validuje neduveryhodny vstup,
- co se loguje a co se naopak logovat nesmi,
- jaky negativni nebo security test zmenu kryje.

---

## Pravidla jednotlivych kroku

### 1. Idea

- vznikne napad, problem nebo pozadavek
- nejdriv se urci, jestli jde o feature, technicky dluh, parser, bug nebo architektonicke rozhodnuti
- idea se zapise do aktualniho scope, issue nebo backlogu podle priority
- zaznamena se, zda pracuje s citlivymi daty nebo meni attack surface

### 2. Planning

- idea se porovna s roadmapou, scope a business prioritami
- rozhodne se, jestli patri do aktualni faze nebo backlogu
- u male zmeny muze byt planning omezen na jasny issue nebo PR popis
- u vyznamne zmeny musi byt znamy owner dat, dopad na moduly, kontrakty a testovaci strategie
- u bezpecnostne relevantni zmeny se urci trust boundary, autorizace, data classification a abuse scenarios

### 3. Decision

- pokud ma vec dlouhodoby dopad, vznikne nebo se upravi ADR
- pokud meni modulove hranice, musi byt zapsana v architecture dokumentech
- pokud meni bezpecnostni model, auth, retention, kryptografii nebo spravu secrets, musi byt rozhodnuti explicitne zaznamenane
- ADR se nevytvari pro bezne implementacni detaily bez dlouhodobeho dopadu

### 4. Implementation

- implementuje se az po dostatecnem uzavreni potrebne planning a decision casti
- kod musi respektovat moduly, source of truth, coding standards a security strategy
- autorizace se implementuje na backendu, ne pouze v UI
- neduveryhodne vstupy se validuji na vstupni hranici a znovu tam, kde to vyzaduje domenovy invariant
- secrets ani citliva data se nesmi dostat do repozitare, klienta nebo logu
- generovane soubory se neupravuji rucne
- docasne adaptery a migracni zkratky musi byt explicitne oznacene a mit plan odstraneni

### 5. Tests

- nova logika bez odpovidajicich testu neni hotova
- parser a vypocetni opravy musi mit regression ochranu
- zmena API kontraktu musi mit contract nebo integration test
- account-level operace musi mit negativni test s cizim uzivatelem
- importy a parsery musi mit malformed, limit a zlomyslne vstupni scenare podle rizika
- auth a session zmeny musi testovat expiry, revocation a neopravneny pristup
- migrace databaze musi byt overitelna dopredu i z pohledu rollback nebo recovery postupu

### 6. Review

- kontroluje se spravnost, scope fit, modulove hranice, bezpecnost a testy
- review kontroluje autorizaci, account isolation, validaci vstupu, logovani citlivych dat a zachazeni se secrets
- u vyznamne zmeny se kontroluje soulad s ADR a architecture dokumenty
- pokud chybi nutne rozhodnuti nebo security posouzeni, review vraci zmenu do planning nebo decision kroku

### 7. Merge

- merge prichazi az po review a uspesnych testech
- branch musi byt v souladu s aktualnim target branchem
- PR musi jasne popsat dopad, zpusob overeni a pripadne navazujici praci
- kriticky nebo vysoky znamy bezpecnostni problem nesmi byt mergovan bez explicitne schvalene, casove omezene vyjimky

### 8. Release

- release se ridi podle release strategy, security strategy a aktualni faze produktu
- zmena, ktera vyzaduje migraci, feature flag nebo postupny rollout, musi mit tento postup pripraveny pred releasem
- podle faze produktu musi probehnout dependency scan, secret scan a odpovidajici security testy
- produkcni release je blokovan otevrenym kritickym nebo vysokym bezpecnostnim nalezem

---

## Definition of Done pro zmenu

Zmena je hotova, kdyz:

- implementace odpovida schvalenemu scope
- vlastnictvi dat a modulove hranice zustaly jasne
- autorizace a account isolation jsou vyresene tam, kde jsou relevantni
- vstupy, soubory a externi data jsou validovane podle rizika
- logy neobsahuji secrets ani zbytecna citliva data
- testy odpovidaji funkcni i bezpecnostni urovni rizika a prochazeji
- dokumentace a ADR jsou aktualizovane, pokud je zmena ovlivnila
- nejsou ponechane nezdokumentovane docasne zkratky nebo bezpecnostni vyjimky
- PR popisuje, jak byla zmena funkcne a bezpecnostne overena

---

## Zakladni pravidlo

Pokud neni jasne, kam vec patri, podle jakeho pravidla se ma udelat nebo jaky ma bezpecnostni dopad, workflow se vraci zpet do planning nebo decision vrstvy. Proces ale nema vytvaret administrativu pro male zmeny, ktere nemeni kontrakty, vlastnictvi dat, architekturu ani attack surface.