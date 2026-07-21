# Návrh řešení: [název]

Implementaci zatím neprováděj.

## Problém a cíl

Stručně popiš současný stav, požadovaný výsledek a proč je změna potřeba.

## Kontext

Načti `AGENTS.md` a pouze uvedené relevantní dokumenty/soubory: [seznam].

## Varianty

Navrhni nejvýše tři realistické varianty. U každé uveď dopad na vrstvy, data/kontrakty, bezpečnost, testování, migraci/rollback a složitost.

## Doporučení

Vyber jednu variantu, vysvětli trade-offy a označ všechna rozhodnutí, která vyžadují potvrzení nebo ADR.

## Rozpad

Rozděl doporučenou variantu na kroky S/M. Každý krok musí mít jeden výsledek, závislosti, riziko, akceptační kritéria, relevantní soubory a doporučený model.

## Povinné kontroly finance-app

- Je Python API source of truth a transportní vrstva tenká?
- Zůstává migration ownership jednoznačný (aktuálně Prisma do explicitního cutoveru)?
- Je account isolation v backendu?
- Jsou `Decimal`, měna, event-date FX a zaokrouhlení explicitní?
- Jsou importy, rollback, idempotence a souběh pokryty podle rizika?
- Neuniknou citlivá data do logů?
