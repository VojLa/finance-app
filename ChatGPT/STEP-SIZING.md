# Velikost implementačních kroků

Velikost neurčuje jen počet řádků. Rozhoduje počet nezávislých chování, vrstev, rizik a možnost samostatného ověření.

## XS – mechanická změna

1–3 soubory, bez změny veřejného API, schématu nebo architektury. Překlep, dokumentace, lokalizovaný test či konfigurace. Bez samostatného plánu.

## S – malá funkční změna

2–6 souborů, jedno jasné chování a nízké riziko. Například validace existujícího pole nebo lokalizovaná oprava služby včetně testu. Levný až střední model.

## M – standardní vertikální řez

Obvykle 5–12 souborů a jedna business schopnost přes nutné vrstvy. Například nový FastAPI endpoint s Pydantic schématem, service/repository změnou, autorizací a integračními testy. Toto je preferovaná maximální implementační jednotka.

## L – komplexní změna

Více spolupracujících schopností, zásadní změna schématu, auth hranice, import pipeline nebo peněžního modelu. Neimplementovat jedním promptem. Rozdělit na návrh, kontrakty/rozhraní, implementační řezy, kompatibilitu/migraci, integrační testy a odstranění staré cesty.

## XL – epic

Například celý import, přepis backendu, migrace Prisma → Alembic nebo kompletní autentizace. XL se pouze rozpadá pomocí `templates/EPIC.md`.

## Skóre složitosti

Přičti: každá aplikační vrstva +1; veřejné API +1; externí integrace +2; migrace/ownership +3; auth/autorizace +3; peněžní výpočet +3; souběh/background job +3; zpětná kompatibilita +2; více než 10 souborů +2; neuzavřené architektonické rozhodnutí +3.

- 0–2: XS/S
- 3–5: S/M
- 6–8: M
- 9–12: L, nejdřív plán a rozpad
- 13+: XL, povinně rozdělit

## Povinné dělení

Rozděl krok, pokud obsahuje více než jednu nezávislou funkci, mění zároveň architekturu i business chování, vyžaduje více migračních rozhodnutí, má přes 8 nezávislých akceptačních kritérií nebo jej nelze bezpečně vrátit jedním srozumitelným rollbackem.
