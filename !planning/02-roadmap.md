# Roadmap

## Smysl roadmapy

Tato roadmapa prevadi scope verzi `0.1` az `0.5` do praktickeho poradi prace. Neni to seznam vsech napadu. Je to ridici dokument, ktery urcuje:

- co delat driv a co az pozdeji,
- proc je dana faze dulezita,
- co musi byt hotove, aby dalsi faze davala smysl,
- kde je nejvetsi riziko pro produkt i architekturu.

Cilem je dostat aplikaci od planovaciho zakladu pres interni architektonicke MVP az k produkcnimu MVP bez toho, aby se preskakovaly zavislosti nebo vracela business logika zpet do `Next.js`.

---

## Roadmap principy

- Nejdriv planovaci a rozhodovaci zaklad.
- Potom architektura a backendova hranice.
- Potom spravnost dat.
- Potom realna pouzitelnost.
- Potom beta stabilita a provozni minimum.
- Nakonec produkcni MVP.

Kazda dalsi faze predpoklada, ze predchozi faze je opravdu uzamcena. Pokud nejsou stabilni data, nema smysl polish UI. Pokud neni stabilni auth a provoz, nema smysl mluvit o produkcnim MVP.

---

## Faze roadmapy

### 0.0 - Planning

Ucel:
Uzamknout produktovy a architektonicky zaklad pred samotnou implementaci.

Co musi byt hotove:

- `Vision`,
- `Modules`,
- `Domain Model`,
- `Roadmap`,
- `Scope`,
- `Architecture`.

Proc je tato faze uplne prvni:
Bez predem rozhodnutych hranic se implementace rychle rozjede do chaosu a zacne se architektura prepisovat za pochodu.

Hlavni rizika:

- nejasna vize produktu,
- chybejici hranice mezi moduly,
- scope bez priorit,
- implementace pred rozhodnutim zakladnich pravidel.

---

### 0.1 - Architecture Locked

Ucel:
Overit cilovou architekturu a dokoncit hlavni backendovy prechod pro MVP do `Python API`.

Co musi byt hotove:

- `Next.js` zustava frontend vrstva.
- `Python API` je hlavni backend pro import, portfolio, dashboard a snapshots.
- Kriticka business logika neni source of truth v `Next.js`.
- Import -> ledger -> holdings -> snapshots -> portfolio/dashboard funguje end-to-end.
- Existuje zakladni testovaci a lokalni vyvojove minimum.

Proc je tato faze prvni:
Pokud neni jasna backendova hranice, vsechno dalsi by se stavelo na docasnem nebo nestabilnim zakladu.

Hlavni rizika:

- nejasne rozdeleni odpovednosti mezi `Next.js` a `Python API`,
- duplikace business logiky,
- nestabilni DB a read model hranice.

---

### 0.2 - Data Trusted

Ucel:
Uzamknout spravnost cisel a datovych pravidel.

Co musi byt hotove:

- parsery pro hlavni zdroje jsou stabilni nad realnymi exporty,
- ledger, holdings, cash, FX a snapshots jsou konzistentni,
- `investovano`, `vlozeno`, `cash` a `P&L` jsou reprodukovatelne,
- portfolio a dashboard vraceji stejna cisla nad stejnymi daty,
- fixture datasety a automaticke validace pokryvaji hlavni datove scenare.

Proc tato faze nasleduje po `0.1`:
Architektura bez duveryhodnych dat nestaci. Dokud neverime cislum, nelze aplikaci realne pouzivat.

Hlavni rizika:

- rozdilne interpretace stejnych transakci,
- nekonzistentni FX prepocet,
- chyby v historii portfolia a snapshot logice,
- ztracene nebo spatne interpretovane parse issues.

---

### 0.3 - Internal Product

Ucel:
Udelat z technicky spravne aplikace realne pouzitelny interni nastroj.

Co musi byt hotove:

- import workflow je srozumitelny a asynchronni,
- portfolio a dashboard jsou citelne a ergonomicke,
- existuje zakladni account management,
- aplikace ma vyrazne sirsi importni pokryti,
- podporuje vsechny hlavni instituce cilove skupiny nebo pro ne ma realisticky pouzitelny fallback,
- existuje `custom CSV` fallback pro nepodporovane instituce,
- pridani noveho parseru trva maximalne nekolik hodin, ne dny nebo refaktor cele importni vrstvy,
- existuji navody pro export CSV z podporovanych instituci i pro vytvoreni vlastniho `custom CSV`.

Proc tato faze nasleduje po `0.2`:
Pouzitelnost ma smysl teprve ve chvili, kdy se uzivatel muze oprit o spravna data.

Hlavni rizika:

- aplikace funguje jen pro maly pocet zdroju,
- import je technicky spravny, ale nepouzitelny pro bezneho uzivatele,
- chybove stavy a fallbacky jsou nejasne.

---

### 0.4 - Beta Ready

Ucel:
Pripravit aplikaci na prvni skutecne uzivatele mimo uzky vyvojovy kruh.

Co musi byt hotove:

- stabilni auth/session hranice mezi frontendem a `Python API`,
- account isolation a user boundary jsou spolehlive,
- importy, snapshoty a dlouhe joby jsou dohledatelne,
- existuje zakladni monitoring, logovani a retry/rebuild workflow,
- konfigurace, nasazeni a recovery postupy jsou zdokumentovane,
- aplikace ma support minimum pro private beta provoz.

Proc tato faze nasleduje po `0.3`:
Nejdriv musi byt aplikace pouzitelna, teprve potom se vyplati investovat do beta stability a provozni discipliny.

Hlavni rizika:

- uzivatel vidi cizi data nebo nestabilni session stav,
- chyby nejdou dohledat,
- beta provoz stoji na rucni improvizaci.

---

### 0.5 - Production Ready

Ucel:
Dodat prvni produkcne pouzitelne MVP v jasne ohranicenem scope.

Co musi byt hotove:

- hlavni workflow od prihlaseni po portfolio funguje stabilne,
- `Python API` je produkcni backend pro core workflow,
- importni zdroje v podporovanem scope jsou spolehlive,
- portfolio, dashboard, cash, snapshots a hlavni account pohledy jsou duveryhodne,
- monitoring, error tracking, rollback a troubleshooting existuji,
- scope MVP je jasne komunikovany a neumi "potichu selhat".

Proc tato faze nasleduje po `0.4`:
Produkcni MVP vyzaduje nejen funkcnost, ale i provozni jistotu a jasne hranice produktu.

Hlavni rizika:

- nerealisticky siroky scope,
- stale slaba duvera v data,
- chybejici provozni pripravenost,
- neukotvena hranice mezi podporovanym a nepodporovanym chovanim.

---

## Prioritni poradi prace

### Vlna 1

- Uzamknout `0.0`.
- Dokoncit planning dokumenty a hlavni rozhodnuti.
- Dokoncit `0.1`.
- Ujasnit vsechny hlavni backend kontrakty mezi frontendem a `Python API`.
- Dokoncit hlavni import -> snapshot -> portfolio tok bez zavislosti na stare `Next.js` logice.

### Vlna 2

- Dokoncit `0.2`.
- Vytvorit fixture datasety a parity testy.
- Sjednotit portfolio, dashboard a snapshot pravidla.

### Vlna 3

- Dokoncit `0.3`.
- Pokryt hlavni instituce cilove skupiny.
- Navrhnout a zdokumentovat `custom CSV` fallback.
- Dodat navody pro exporty z podporovanych instituci.
- Zajistit, aby pridani noveho parseru bylo rychle a predvidatelne.
- Dotahnout ergonomii hlavniho workflow.

### Vlna 4

- Dokoncit `0.4`.
- Stabilizovat auth/session hranici.
- Dodat monitoring, logovani a beta support minimum.
- Ujasnit retention, recovery a provozni procesy.

### Vlna 5

- Dokoncit `0.5`.
- Uzavrit podporovany produkcni scope.
- Dotahnout produkcni spolehlivost a release readiness.

---

## Zavislosti mezi fazemi

- `0.1` je blokovana neuzavrenou `0.0`, pokud stale neni rozhodnuta vize, scope nebo modulove hranice.
- `0.2` je blokovana nedokoncenou `0.1`, pokud backend stale nema jasnou source of truth.
- `0.3` je blokovana nedostatecnou duverou v data z `0.2`.
- `0.4` je blokovana, pokud `0.3` stale vyzaduje technicke obchazky pro bezne pouziti.
- `0.5` je blokovana, pokud `0.4` nema dostatecnou provozni disciplinu, auth hranici a beta stabilitu.

---

## Co neni soucasti teto roadmapy

Tato roadmapa zatim neresi detailne:

- `1.0` scope po produkcnim MVP,
- mobilni a desktop klienty,
- sirokou automatickou synchronizaci instituci,
- pokrocile budgeting a planning moduly,
- enterprise nebo high-scale architekturu,
- plny `Rust` rollout napric vypocetni vrstvou.

Tyto oblasti maji prijit az po stabilnim `0.5` nebo jako samostatne navazujici roadmapy.

---

## Nejvetsi projektova rizika

- prerustani scope
- prilis mnoho parseru prilis brzy bez vazby na cilovou skupinu
- predcasna optimalizace
- prilis brzke reseni `Rustu`
- neustale prepisovani architektury
- pridavani novych funkci bez uzavreni predchozi faze

Tato sekce neni formalita. Je to seznam veci, ktere maji byt pravidelne pripominane pri kazde vetsi prioritizaci.

---

## Definice uspechu roadmapy

Roadmapa je naplnovana spravne ve chvili, kdy:

- dalsi faze nikdy nestoji na neoverenem zakladu,
- scope kazde verze je jasne odlisena,
- produktove a technicke priority se nerozjizdeji proti sobe,
- aplikace se krok za krokem posouva od architektonickeho MVP k realne nasaditelnemu produktu.
