# Review diffu: [krok/PR]

Zkontroluj pouze přiložený STEP, diff a výsledky testů. Neimplementuj opravy.

## Priorita review

1. Ztráta/poškození dat, chybný peněžní výpočet, bezpečnost a account isolation.
2. Nesplněné chování, API/DB kompatibilita, transakce, rollback, idempotence a souběh.
3. Chybějící nebo falešně pozitivní testy.
4. Modulové hranice, duplicita a udržovatelnost.
5. Styl pouze tehdy, když má praktický dopad.

## Kontrolní otázky

- Odpovídá diff přesně rozsahu a akceptačním kritériím?
- Provádí backend object-level autorizaci i pro cizí resource ID?
- Jsou ORM dotazy správně scopeované na účet?
- Používají peníze `Decimal`, explicitní měnu/zaokrouhlení a správný historický FX okamžik?
- Je migration ownership zachovaný a nevzniká drift Prisma/SQLAlchemy/Alembic?
- Jsou API chyby stabilní a OpenAPI kontrakt otestovaný?
- Nezapisují se secrets, tokeny nebo raw finanční payloady do logů?
- Kryjí testy negativní, rollback a concurrent scénáře podle rizika?

## Formát nálezů

Pro každý nález uveď prioritu P0–P3, konkrétní soubor/řádek, důkaz, dopad a nejmenší doporučenou opravu. Neuváděj spekulativní nebo čistě stylistické nálezy. Pokud žádný věcný nález není, napiš to explicitně a uveď zbytková rizika či chybějící ověření.
