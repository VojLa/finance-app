# ADR 0001 - Python jako primarni backend

Status: Accepted
Date: 2026-07-16
Decision owners: VojLa
Supersedes: none
Superseded by: none

## Kontext

Soucasna aplikace obsahuje frontend i vyznamnou cast backendove logiky v `Next.js` a `TypeScriptu`. Dlouhodobym cilem je oddelit klientskou vrstvu od financni business logiky a umoznit rozvoj backendu v ekosystemu vhodnem pro datove zpracovani, parsery, analytiku a testovani.

## Rozhodnuti

`Python API` bude primarni backend aplikace.

- `FastAPI` bude HTTP a API vrstva.
- Business logika bude vlastnena domenovymi moduly v Pythonu.
- `Next.js` zustane frontendem a pripadne docasnym adapterem behem migrace.
- Nova kriticka business logika se nebude pridavat do `Next.js` route handleru.
- Rust muze byt pozdeji pouzit pro meritelne vykonove tezke deterministicke vypocty.

## Dusledky

Pozitivni:

- jasna hranice mezi frontendem a backendem,
- jeden vlastnik financnich pravidel,
- vhodne prostredi pro parsery, jobs a datove workflow,
- stejny backend pro web, mobilni i desktop klienty.

Negativni:

- docasne hybridni prostredi,
- nutnost migrovat existujici TypeScript business logiku,
- provoz dvou technologickych ekosystemu.

## Zamitnute alternativy

- ponechat cely backend v `Next.js`,
- prepsat celou aplikaci jednorazove bez migracniho obdobi,
- pouzit Rust jako primarni API a orchestracni jazyk.

## Migracni nebo rollout plan

1. Vytvorit zaklad `Python API`.
2. Definovat modulove hranice a API kontrakty.
3. Presouvat workflow po vertikalnich use-casech.
4. Nechat `Next.js` jako docasny adapter tam, kde migrace jeste neni hotova.
5. Odstranit puvodni backendovou logiku po overeni parity a testu.
