# Documentation principles and network

Type: reference
Status: implemented
Owns: pravidla vlastnictví, životního cyklu a propojení dokumentů
Code: dokumentační kořeny a `scripts/docs`
Update when: změní se dokumentační autorita, síť nebo životní cyklus

## Jeden fakt, jeden vlastník

| Informace                      | Autoritativní vlastník             |
| ------------------------------ | ---------------------------------- |
| Aktuální business význam       | doménový `README.md`               |
| Přesné znění invarianty        | invariant catalog                  |
| Hranice runtime modulu         | module card                        |
| Průchod přes více modulů       | flow dokument                      |
| Soubory, routy, modely a testy | generated inventory                |
| Testovací záměr a riziko       | doménový test matrix               |
| Přesný HTTP kontrakt           | OpenAPI                            |
| Fyzické DB objekty             | Alembic, SQLAlchemy a DB inventory |
| Důvod dlouhodobého rozhodnutí  | ADR                                |
| Budoucí stav                   | `!planning/`                       |
| Postup pro uživatele           | `!user-docs/`                      |
| Milestone a auditní důkaz      | historie                           |

Doména může shrnout dopad invarianty jednou větou, ale odkazuje na její jediné
přesné znění. Module card neudržuje úplný file list. Test matrix nevyjmenovává
všechny testovací soubory.

## Oddělení času a publika

- `!docs/` popisuje pouze implementovaný systém.
- `!planning/` obsahuje návrhy, roadmapu a neimplementované scope.
- `!user-docs/` vysvětluje produkt bez interních implementačních detailů.
- `ChatGPT/` obsahuje historickou pracovní a auditní evidenci; aktivní Codex
  workflow vlastní `.agents/`.
- `!docs/map/generated/` obsahuje pouze deterministické výstupy.

`Status: proposed` je povolen pouze v `!planning`. Historický dokument nesmí být
čtecím předpokladem pro běžný vývojový úkol.

## Identita ručního dokumentu

Každý významový dokument kromě velmi malého README začne blokem:

```text
Type: domain | module | flow | invariant | testing | runbook | reference
Status: current | proposed | historical
Owns: jedna věta určující vlastněnou informaci
Code: hlavní runtime hranice, ne úplný seznam souborů
Update when: konkrétní změna, která vyvolá DOC IMPACT
```

Stabilní ID používají prefixy `DOM`, `MOD`, `FLOW`, `INV`, `TEST`, `RUN` a
`ADR`. Test matrix tak odkazuje na invariant bez kopírování pravidla.

## Délka

| Typ                      |    Cíl | Rozdělit při |
| ------------------------ | -----: | -----------: |
| README                   | 40–100 |  120 řádcích |
| Project/domain mapa      | 80–160 |  200 řádcích |
| Domain nebo module       | 60–180 |  220 řádcích |
| Flow, invariant, testing | 80–160 |  200 řádcích |
| Runbook nebo ADR         | 80–200 |  250 řádcích |

500 řádků zůstává hard limit. Dokument se dělí podle vlastníka a tématu, ne
pouze mechanicky podle délky.

## Cílová síť

```text
!docs/
├── README.md
├── map/{project-map/, domain-map/, generated/}
├── architecture/{boundaries/, flows/, invariants/}
├── domains/<domain>/{README.md, modules/, flows/, testing.md}
├── api/
├── data/
├── testing/
├── security/
├── operations/
├── decisions/
├── reference/
└── history/
```

Každý adresář má skutečný `README.md`: odkazuje o jednu úroveň níže, zpět na
rodiče a na několik přímých sousedních vlastníků. Doporučená cesta je:

```text
AGENTS → L0 map → L1 domain row → domain README
       → invariant/flow/module → relevantní kód a testy
```
