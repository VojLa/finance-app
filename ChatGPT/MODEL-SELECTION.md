# Volba modelu a eskalace

Názvy a ceny modelů se mění; vybírej podle schopnosti a rizika, ne podle konkrétního obchodního názvu.

## Levný model

Použij pro XS/S, dokumentaci, mechanické změny, doplnění známých testů a review malého jednoznačného diffu. Zadání musí obsahovat přesné soubory, rozsah a akceptační kritéria.

## Střední model

Výchozí volba pro M: jeden vertikální řez přes FastAPI, Pydantic, service/repository, SQLAlchemy a testy. Vhodný také pro lokalizovanou diagnostiku a tvorbu kvalitních integračních testů.

## Silný model

Použij pro návrh L/XL, nejasné architektonické hranice, auth a account isolation, peněžní invarianty, databázový ownership/cutover, souběh, importní bezpečnost a review vysoce rizikového diffu. Silný model má primárně uzavřít rozhodnutí a rozdělit práci; rutinní podkroky potom vrať střednímu modelu.

## Eskalační pravidlo

1. Zkontroluj, zda je zadání úzké a obsahuje relevantní soubory.
2. Doplň chybějící kontrakt, reprodukci nebo očekávané chování.
3. Po jednom neúspěchu stejné kategorie přejdi z levného na střední.
4. Na silný model přejdi při neuzavřeném návrhovém rozhodnutí, vysokém riziku nebo po dvou věcně chybných pokusech.
5. Neopakuj stejný prompt; nejdřív odstraň příčinu nejasnosti.

## Úspora kreditů

- Nech nástroje spouštět testy; modelu dej jen relevantní chybu.
- Pro review posílej diff, STEP a výsledky kontrol, ne celý repozitář.
- Stabilní pravidla odkazuj z `AGENTS.md`, `memory/` a `!planning/` místo kopírování.
- Plán nevytvářej pro XS a jednoznačné S.
- Po změně rozsahu založ nový krok; nenabaluj další požadavky do rozpracovaného promptu.
