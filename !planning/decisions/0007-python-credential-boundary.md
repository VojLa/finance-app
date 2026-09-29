# ADR 0007 - Python credential boundary with NextAuth sessions

Status: Accepted
Date: 2026-08-09
Decision owners: VojLa
Supersedes: none
Superseded by: none

## Kontext

NextAuth spravuje browser session, ale jeho credentials provider dosud cetl uzivatele
pres Prisma a overoval i menil bcrypt hash v Next.js. To vytvarelo druheho vlastnika
identity dat vedle ciloveho Python backendu. Registrace navic nemela jednotnou
normalizaci emailu ani autoritativni serverovou politiku hesel.

Pri prihlaseni jeste neexistuje uzivatelska session, takze bezny interni token s
persistovanym user ID nelze pouzit pro credential verify ani registraci. Verejny
nechraneny Python endpoint by naopak rozsiril utocnou plochu.

## Rozhodnuti

Python je jedinym vlastnikem credential operaci a `passwordHash`:

- `POST /api/v1/auth/credentials/verify` overi email a heslo;
- `POST /api/v1/auth/register` vytvori uzivatele;
- `PUT /api/v1/auth/password` overi stare a ulozi nove heslo prihlaseneho uzivatele;
- NextAuth nadale vlastni pouze JWT session a jeji mapovani do interni identity;
- Next.js auth routy jsou tenke same-origin adaptery a nepristupuji do databaze.

Credential verify a registrace vyzaduji kratkodoby podepsany interni token s presnym
servisnim subjectem `finance-app-next-auth-service`. Tento token nesmi byt povazovan
za uzivatele a bezne user endpointy jej neautorizuji. Zmena hesla vyzaduje standardni
databazove overenou user identity.

Email se normalizuje trimem a lowercase v Pythonu. Nova hesla maji nejmene osm znaku
a nejvyse 72 UTF-8 bajtu, protoze bcrypt dalsi bajty nerozlisuje. Python zapisuje
bcrypt cost 12 a musi overit existujici `$2a$`/`$2b$` hashe vytvorene `bcryptjs`.
Chybejici uzivatel a chybne heslo maji stejny verejny kod i bcrypt-cost cestu.

Hranice je pripravena pro rate limit podle endpointu, zdrojove adresy a normalizovane
identity, ale aplikace nema zavest procesove pocitadlo, ktere by lhalo ve vice
instancich. Soucasne lokalni osobni nasazeni spoleha na neveřejnou Python sit a
Next.js same-origin vstup. Pred verejnym nebo viceuzivatelskym nasazenim je povinny
sdileny ingress/distributed rate limit a tato kontrola je release blocker.

Auditni log auth operaci obsahuje pouze request ID, metodu, cestu, status a dobu.
Email, heslo, hash, Authorization a Cookie se neloguji.

## Dusledky

Pozitivni:

- credential zapis a validace maji jednoho vlastnika;
- Next.js nepotrebuje Prisma ani bcrypt pro produkcni autentizaci;
- OpenAPI je source of truth pro auth request/response kontrakty;
- chyby neprozrazuji existenci emailu a hashe neopousteji Python.

Negativni:

- prihlaseni zavisi na dostupnosti Python API;
- servisni token sdili interni podpisovy klic s user bridge a musi mit striktni
  subject kontrolu;
- verejne nasazeni potrebuje sdileny rate limiter mimo proces aplikace.

## Zamitnute alternativy

- ponechat bcrypt a Prisma v NextAuth;
- zpristupnit credential endpoint bez server-to-server autentizace;
- pouzit falesne user ID a nechat jej projit beznou persisted-user autorizaci;
- pridat in-memory limit, ktery se resetuje pri restartu a nefunguje mezi instancemi;
- prejit na jiny hash algoritmus bez migrace existujicich bcrypt hashu.

## Migracni nebo rollout plan

1. Pridat Python use cases, bezpecne kontrakty a PostgreSQL testy.
2. Vygenerovat TypeScript OpenAPI kontrakt a pridat server-only adapter.
3. Prepojit NextAuth, registraci a zmenu hesla.
4. Prokazat kompatibilitu existujiciho `bcryptjs` hashe a negativni token/cross-user
   scenare.
5. Odstranit z produkcniho TypeScript auth kodu Prisma a bcrypt.
6. Pred verejnym nasazenim nakonfigurovat sdileny rate limit a provozni alerty.
