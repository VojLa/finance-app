# Planning

Status: `0.0 - Planning` completed on 2026-07-16
Current phase: `0.1 - Architecture Locked`

Tato slozka obsahuje kompletni navrh produktu, architektury, bezpecnosti a vyvojovych pravidel projektu.

Neni to jen jednorazovy plan. Je to ziva dokumentace, podle ktere se rozhoduje o scope, architekture, implementaci, bezpecnosti a release procesu.

## Doporucene poradi cteni

### Product

1. `product/01-vision.md`
2. `product/02-roadmap.md`
3. `product/04-business.md`
4. `product/10-release-strategy.md`
5. `scope/0.0 - Planning.md`
6. `scope/0.1 - Architecture Locked.md`
7. dalsi soubory ve `scope/` podle aktualni faze

### Architecture

1. `architecture/03-modules.md`
2. `architecture/05-domain-model.md`
3. `architecture/06-project-structure.md`
4. `architecture/07-testing-strategy.md`
5. `architecture/08-api-guidelines.md`
6. `architecture/09-coding-standards.md`
7. `architecture/10-security-strategy.md`
8. `architecture/11-development-workflow.md`

### Decisions

1. `decisions/README.md`
2. jednotliva ADR rozhodnuti podle poradi

## Smysl jednotlivych casti

- `product/` popisuje proc produkt vznika, kam smeruje a jak se bude vydavat
- `architecture/` popisuje jak ma byt system navrzeny a podle jakych pravidel se ma stavet a zabezpecovat
- `decisions/` drzi architektonicka a bezpecnostni rozhodnuti, ktera uz byla prijata
- `scope/` drzi milestone scope a backlog

## Pravidlo pouzivani

Pokud pri vyvoji narazime na nejasnost:

1. nejdriv hledat odpoved v `decisions/`
2. potom v `architecture/`
3. potom v `product/`
4. pokud odpoved neexistuje, dopsat nebo upravit dokumentaci driv, nez se udela velke implementacni nebo bezpecnostni rozhodnuti

Bezpecnostni rozhodnuti se nesmi odkladat az na release. Pokud zmena pracuje s identitou, opravnenim, citlivymi daty, soubory, externi integraci nebo produkcnim pristupem, musi byt vyhodnocena podle `architecture/10-security-strategy.md`.

Po uzavreni `0.0` se nema pridavat dalsi obecna dokumentace bez konkretniho duvodu. Hlavni prace se presouva do implementace scope `0.1 - Architecture Locked`.