# Security Strategy

## Smysl dokumentu

Tento dokument definuje bezpecnostni principy Finance App. Aplikace pracuje s citlivymi financnimi daty, proto bezpecnost neni samostatna funkce pridavana pred releasem. Je to prurezovy pozadavek pro architekturu, implementaci, testovani, provoz i podporu.

Dokument neurcuje pouze pouzite knihovny. Určuje:

- co chranime,
- pred kym a pred cim data chranime,
- kde jsou hlavni trust boundaries,
- jaka pravidla musi splnit kazda faze produktu,
- jak se bezpecnost overuje a jak se reaguje na incident.

---

## Bezpecnostni cile

Prioritami jsou:

1. **Confidentiality** - financni a osobni data vidi pouze opravneny uzivatel a autorizovane procesy.
2. **Integrity** - data a vypocty nelze menit bez autorizace a dohledatelne auditni stopy.
3. **Availability** - aplikace a kriticka data jsou obnovitelna po chybe, utoku nebo selhani infrastruktury.
4. **Account isolation** - jeden uzivatel nikdy nesmi cist ani menit data jineho uzivatele.
5. **Auditability** - kriticke zmeny, importy, administrativni zasahy a bezpecnostni udalosti jsou dohledatelne.
6. **Privacy by design** - sbiraji se pouze data potrebna pro fungovani produktu a maji definovany zivotni cyklus.

---

## Co chranime

### Citliva data

- identita uzivatele,
- prihlasovaci a session data,
- bankovni a investicni ucty,
- transakce a historie portfolia,
- importovane soubory a jejich raw obsah,
- zustatky, prijmy, vydaje a hodnota majetku,
- dokumenty, exporty a budouci integracni tokeny,
- auditni a provozni logy, pokud obsahuji identifikatory nebo financni kontext.

### Kriticke systemove prostredky

- produkcni databaze,
- object storage pro importy a dokumenty,
- secrets a API klice,
- background job queue,
- deployment pipeline,
- administrativni rozhrani,
- zalohy a recovery prostredky.

---

## Threat model

Threat model se musi aktualizovat pri kazde vyznamne zmene trust boundary, autentizace, ukladani souboru, externi integrace nebo administrativniho pristupu.

Minimalne se pocita s temito hrozbami:

- ziskani cizi session nebo prihlasovacich udaju,
- horizontal privilege escalation mezi uzivateli,
- neopravneny administratorsky pristup,
- injection utoky a nebezpecne zpracovani vstupu,
- zlomyslne nebo poskozene CSV a dalsi importni soubory,
- path traversal, formula injection a resource exhaustion pri importu,
- brute-force a credential-stuffing utoky,
- CSRF, XSS a zneuziti cookies,
- SSRF pri budoucich externich integracich,
- unik secrets do repozitare, logu nebo klienta,
- kompromitovana zavislost nebo build pipeline,
- ztrata, poskozeni nebo neopravnena modifikace dat,
- tiche selhani auditu, zaloh nebo monitoringu.

---

## Trust boundaries

Hlavni hranice duvery jsou:

```text
Uzivateluv prohlizec
        |
        v
Next.js frontend
        |
        v
Python API
   |         |
   v         v
PostgreSQL   Background jobs
   |         |
   +----+----+
        v
Object storage / external providers
```

Pravidla:

- zadny vstup z klienta se nepovazuje za duveryhodny,
- frontend nesmi rozhodovat o autorizaci,
- kazdy backend request musi znovu overit identitu a opravneni,
- background job musi nest explicitni security context nebo bezpecne identifikovany systemovy kontext,
- externi provider je neduveryhodna hranice a jeho odpovedi se validuji,
- databaze nesmi byt pristupna primo z verejne site.

---

## Authentication

- autentizace ma jednu vlastnickou hranici v `Auth and Identity`,
- hesla se nikdy neukladaji v citelne podobe a pouziva se moderni password hashing,
- session a tokeny maji omezenou platnost a bezpecny revocation mechanismus,
- cookies maji podle zvolene architektury `HttpOnly`, `Secure` a odpovidajici `SameSite`,
- citlive operace mohou pozdeji vyzadovat step-up autentizaci,
- reset hesla, zmena e-mailu a recovery flow musi byt odolne proti account takeover,
- administrativni a produkcni pristupy musi pouzivat MFA,
- chybove odpovedi nesmi prozrazovat, zda konkretni ucet existuje.

---

## Authorization a account isolation

- autorizace se provadi na backendu pro kazdy request a kazdou business operaci,
- vlastnictvi uctu se overuje pres vztah `user -> account`, ne pouze podle ID z requestu,
- repository dotazy maji byt scopeovane uzivatelem nebo workspace boundary,
- vsechny account-level testy musi obsahovat negativni test s cizim uzivatelem,
- read modely, exporty, joby i websocket nebo polling endpointy musi respektovat stejnou izolaci,
- administratorsky pristup musi byt explicitni, auditovany a oddeleny od bezneho uzivatelskeho toku,
- object-level authorization se nesmi nahrazovat pouze kontrolou role.

---

## Ochrana dat

### Prenos

- produkcni komunikace probiha pouze pres TLS,
- interni sluzby pouzivaji sifrovany prenos, pokud opousteji duveryhodnou runtime hranici,
- citlive hodnoty se neposilaji v URL ani query parametrech.

### Ulozeni

- databaze, zalohy a object storage pouzivaji encryption at rest,
- secrets se neukladaji do Git repozitare ani do frontend bundle,
- citlive importni soubory maji omezeny pristup a definovanou retention,
- exporty maji omezenou platnost nebo autorizovane stazeni,
- logy nesmi obsahovat hesla, tokeny, cele session hodnoty ani zbytecny raw financni obsah.

### Minimalizace a retention

- kazdy typ citlivych dat ma definovany ucel a dobu uchovani,
- raw importni soubor se neuchovava dele, nez je potreba pro audit, opravu nebo zakonny duvod,
- uzivatel musi mit pozdeji definovanou cestu k exportu a odstraneni dat,
- zalohy a auditni data musi mit vlastni retention a deletion pravidla.

---

## Bezpecnost importu a parseru

Import je jedna z nejrizikovejsich hranic produktu.

Povinna pravidla:

- limit velikosti souboru, poctu radku a doby zpracovani,
- allowlist podporovanych typu a konzervativni detekce formatu,
- soubory se nezpracovavaji jako spustitelny obsah,
- parser nema primy zapis do databaze,
- vstup se zpracovava v izolovanem jobu s omezenymi prostredky,
- selhani jednoho importu nesmi shodit worker ani cely system,
- ochrana proti CSV formula injection pri exportu nebo zpetnem zobrazeni,
- raw hodnoty se pri zobrazeni escapují,
- deduplikace a idempotency brani opakovanemu vytvoreni udalosti,
- parser fixtures musi obsahovat poskozene, extremni a zlomyslne vstupy,
- importni soubory a parse issues podléhaji account isolation.

---

## API a webova bezpecnost

- vsechny vstupy validuje Python API pomoci explicitnich schemat,
- pouzivaji se parametrizovane dotazy nebo bezpecna ORM vrstva,
- CORS je omezen na konkretni povolene origins,
- CSRF ochrana odpovida zvolenemu session modelu,
- vystup do HTML se escapuje a nepouziva se neduveryhodne raw HTML,
- Content Security Policy se zavede pred beta provozem,
- security headers se nastavuji centralne,
- autentizacni, importni, exportni a narocne endpointy maji rate limiting,
- chyby nevraceji stack trace ani interni detaily v produkci,
- API ma ochranu proti mass assignment a klient nesmi nastavovat systemova pole,
- kazda operace meniici data ma jasnou autorizaci, auditni kontext a idempotency pravidla, kde je potreba.

---

## Secrets a konfigurace

- secrets se spravuji pres secrets manager nebo zabezpecene environment values,
- `.env` soubory s produkcnimi hodnotami se nikdy necommituji,
- tajne hodnoty se pravidelne rotuji a pri incidentu musi byt mozne je rychle revokovat,
- frontend smi obdrzet pouze hodnoty urcene ke zverejneni,
- CI/CD pouziva minimalni opravneni a oddelene secrets pro jednotliva prostredi,
- produkcni pristupy nejsou sdilene mezi lidmi,
- pristupy se odebiraji okamzite po zmene role nebo odchodu clena tymu.

---

## Dependency a supply-chain security

- zavislosti se pravidelne skenuji na zranitelnosti,
- lock soubory se commituji a aktualizace zavislosti prochazeji review a testy,
- kriticke baliky musi byt aktivne udrzovane a mit jasny duvod pouziti,
- GitHub Actions pouzivaji omezeny `permissions` scope,
- third-party actions se pinuji na duveryhodnou verzi nebo commit,
- build artefakty musi byt reprodukovatelne a dohledatelne ke commitu,
- produkcni release nesmi vznikat z nezkontrolovaneho lokalniho buildu.

---

## Logging, audit a monitoring

Bezpecnostni logy musi umoznit dohledat:

- uspesna a neuspesna prihlaseni,
- reset a zmenu identity nebo pristupovych udaju,
- zamitnute autorizacni pokusy,
- administrativni zasahy,
- vytvoreni exportu a pristup k citlivym souborum,
- neobvykle importni chyby a opakovane zneuzivani endpointu,
- zmeny secrets, deploymentu a produkcni konfigurace.

Pravidla:

- auditni zaznam nesmi obsahovat samotne secrets,
- logy jsou pristupne pouze opravnenym osobam,
- kriticke udalosti maji alerting,
- monitoring rozlisuje provozni chybu, datovou nekonzistenci a bezpecnostni incident,
- systemovy cas musi byt synchronizovany, aby auditni casova osa davala smysl.

---

## Zalohy a obnova

- databaze a kriticke soubory maji automaticke zalohy,
- zalohy jsou sifrovane a pristup k nim je omezeny,
- recovery se pravidelne testuje, nestaci pouze existence zalohy,
- jsou definovany cilove hodnoty RPO a RTO nejpozdeji pred private beta,
- obnova nesmi obejit account isolation, audit ani migracni pravidla,
- incident nebo poskozeni read modelu nesmi znicit canonical historii.

---

## Secure development lifecycle

### Pred implementaci

- urcit citliva data a trust boundary,
- rozhodnout autorizaci a vlastnika dat,
- identifikovat zneuzitelne scenare,
- definovat negativni a security testy.

### Pri implementaci

- pouzivat centralni auth a authorization mechanismy,
- nepsat vlastni kryptografii,
- neukladat secrets ani citliva data do logu,
- respektovat dependency direction a data ownership.

### Pri review

- kontrolovat autorizaci a account isolation,
- kontrolovat validaci vstupu a bezpecne chyby,
- kontrolovat zmenu attack surface,
- kontrolovat zachazeni se secrets, soubory a osobnimi daty.

### Pred releasem

- dependency a secret scan,
- security testy kritickych workflow,
- kontrola konfigurace prostredi,
- overeni zaloh, rollbacku a alertingu podle faze produktu.

---

## Security testing

Minimalni kategorie:

- unit testy authorization rules,
- integration testy account isolation,
- negativni testy pro cizi resource ID,
- testy session expiry a revocation,
- testy rate limitu na citlivych endpointech,
- fuzz a malformed-input testy parseru,
- testy velikostnich a casovych limitu importu,
- dependency a secret scanning v CI,
- SAST a zakladni DAST pred produkcnim MVP,
- manualni security review pred private beta a produkcnim releasem.

Security test nesmi overovat pouze happy path. Musi dokazat, ze neautorizovana nebo zlomyslna operace selze bez uniku dat.

---

## Incident response

Pred private beta musi existovat minimalni postup:

1. detekovat a klasifikovat incident,
2. omezit dopad a revokovat kompromitovane pristupy,
3. zachovat auditni dukazy,
4. opravit pricinu a obnovit bezpecny provoz,
5. vyhodnotit dotcena data a uzivatele,
6. provest post-incident review a regression ochranu.

Kontakty, odpovednosti a komunikacni povinnosti se doplni pred vstupem skutecnych uzivatelu.

---

## Bezpecnost podle roadmapy

### 0.1 - Architecture Locked

- jedna auth a authorization hranice,
- account isolation zakotvena v repository a service pravidlech,
- secrets nejsou v kodu,
- bezpecna validace API a importnich vstupu,
- zakladni security testy kritickeho end-to-end toku.

### 0.2 - Data Trusted

- integrita canonical dat a audit oprav,
- idempotency importu a jobu,
- testy zlomyslnych a poskozenych parser vstupu,
- ochrana proti tiche modifikaci nebo ztrate dat.

### 0.3 - Internal Product

- centralni rate limiting pro rizikove endpointy,
- bezpecne ukladani a retention importnich souboru,
- security headers a CSP priprava,
- zakladni privacy a deletion pravidla.

### 0.4 - Beta Ready

- threat model review,
- MFA pro administrativni a produkcni pristupy,
- monitoring bezpecnostnich udalosti,
- otestovane zalohy a recovery,
- minimalni incident response,
- manualni security review pred private beta.

### 0.5 - Production Ready

- SAST, dependency a secret scanning v release pipeline,
- zakladni DAST nebo ekvivalentni aplikacni security test,
- overeny rollback, incident response a access review,
- uzavrene kriticke a vysoke bezpecnostni nalezy,
- zdokumentovana privacy, retention a deletion pravidla.

---

## Povinne bezpecnostni zasady

- Bezpecnost se neodklada na konec roadmapy.
- Frontend nikdy neni autoritou pro autorizaci.
- Kazdy account-level pristup se overuje na backendu.
- Zadny secret nesmi byt v repozitari, logu nebo klientskem bundle.
- Citliva data se nesmi logovat bez prokazatelneho duvodu a redakce.
- Parser a importni soubor jsou neduveryhodny vstup.
- Kazda kriticka zmena musi byt auditovatelna.
- Zalohy jsou povazovany za funkcni az po uspesnem testu obnovy.
- Kriticka nebo vysoka zranitelnost blokuje produkcni release.
- Vyjimka z bezpecnostniho pravidla musi byt explicitne zdokumentovana, casove omezena a vlastnena konkretni osobou.
