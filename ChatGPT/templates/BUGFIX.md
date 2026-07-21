# Oprava chyby: [název]

## Pozorované chování

Přesná chyba, prostředí, vstup a skutečný výsledek. Přilož minimální relevantní log bez secrets/citlivých dat.

## Očekávané chování

Uveď zdroj pravdy: test, kontrakt, doménové pravidlo nebo rozhodnutí.

## Reprodukce

Minimální deterministické kroky. Pokud chyba není reprodukovatelná, nejdřív vytvoř diagnostický krok bez změny produkčního chování.

## Hypotéza a kořenová příčina

Odděl důkaz od domněnky. Urči vrstvu, ve které chyba vzniká, a proč ji stávající testy nezachytily.

## Rozsah opravy

Nejmenší změna odstraňující příčinu. Zakázán je nesouvisející refaktoring nebo rozšíření funkcionality.

## Regression test

Nejdřív přidej test, který na původní implementaci selže a po opravě projde. Pro finanční chybu použij přesné `Decimal` hodnoty; pro access bug cizího uživatele; pro import malformed/limit fixture; pro DB chybu rollback a případně souběh.

## Akceptační kritéria

- [ ] Reprodukce před opravou selhává.
- [ ] Regression test po opravě prochází.
- [ ] Nezměnily se nesouvisející kontrakty.
- [ ] Relevantní quality gate prošla.
- [ ] Výstup odpovídá `IMPLEMENTATION-OUTPUT.md`.
