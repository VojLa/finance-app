# Finance App — Development Checklist

Checklist položek z [`finance_app_development_roadmap.md`](./finance_app_development_roadmap.md).

---

## Phase 0 — System Design & Architecture

- [/] Definovat doménový model a entity (User, Account, Transaction, ...)
- [ ] Definovat finanční koncepty (typy transakcí, holdingů, účtů, assetů)
- [ ] Navrhnout currency system (base currency, FX strategie, historické kurzy)
- [ ] Navrhnout import pipeline flow (CSV → parser → validate → dedup → DB → analytics)
- [ ] Vytvořit architecture diagramy
- [ ] Vytvořit ER diagramy
- [ ] Zdokumentovat module strukturu a data flow

---

## Phase 1 — Technical Scaffold

- [ ] Next.js 14 + TypeScript
- [ ] Prisma + PostgreSQL
- [ ] TailwindCSS
- [ ] ESLint / Prettier
- [ ] Module-based složková struktura (`src/modules/`, `src/lib/`, `src/components/`, `src/types/`)
- [ ] Základní routing (dashboard, transactions, accounts, portfolio, settings, import)
- [ ] Docker setup

---

## Phase 2 — Database Layer

- [ ] Prisma schema s Decimal místo Float pro všechna finanční pole
- [ ] Proper constraints (unique indexy, composite keys, relation integrity)
- [ ] ImportBatch model (checksum dedup, userId, accountId, source)
- [ ] ExchangeRate model
- [ ] Prisma migrations
- [ ] Seed data / mock development data

---

## Phase 3 — Accounts & Transactions

- [ ] Přehled účtů (seznam, zůstatky)
- [ ] Přehled transakcí (seznam, filtrace, stránkování)
- [ ] Vytvoření účtu (UI formulář)
- [ ] Editace účtu
- [ ] Smazání účtu
- [ ] Vytvoření transakce (UI formulář)
- [ ] Editace transakce
- [ ] Smazání transakce
- [ ] Detail transakce
- [ ] Přiřazení kategorie k transakci
- [ ] Výchozí kategorie (seed)
- [ ] Vlastní kategorie (CRUD)
- [ ] Podkategorie

---

## Phase 4 — Raiffeisenbank Import System

- [ ] Drag & drop upload
- [ ] Raiffeisenbank CSV parser (encoding, BOM, edge cases)
- [ ] Deduplication (transactionRef)
- [ ] Automatická kategorizace (counterparty → kategorie)
- [ ] Import pipeline přes `importCsv()` + ImportBatch záznam
- [ ] CSV preview před importem
- [ ] Validační chyby zobrazené uživateli
- [ ] Import confirmation dialog

---

## Phase 5 — Budgeting Dashboard

- [ ] Dashboard s přehledem (zůstatky, transakce)
- [ ] Budget progress widgety
- [ ] Graf výdajů (pie chart)
- [ ] Měsíční trendy / přehled
- [ ] Income vs expense graf
- [ ] Net worth summary widget
- [ ] Nedávné transakce widget na dashboardu

---

## Phase 6 — Portfolio Engine

- [ ] Investment transaction system (buy, sell, dividend, staking, fee, currency conversion)
- [ ] Holdings engine (quantity, avgBuyPrice, recalkulace po importu)
- [ ] Realized / unrealized P&L výpočty
- [ ] Alokace portfolia
- [ ] Multi-currency podpora (CZK, EUR, USD) s FX konverzí
- [ ] Historické snapshoty (portfolio value over time)
- [ ] Net worth history (cash + portfolio dohromady)
- [ ] Historické alokace

---

## Phase 7 — Trading212 & Anycoin Imports

- [ ] Trading212 CSV parser (buy, sell, dividendy, currency conversion, interest)
- [ ] Anycoin pairing logic (trade payment + trade fill → InvestmentTransaction)
- [ ] Automatická recalkulace holdings po importu
- [ ] Import pipeline přes `importCsv()` + ImportBatch záznam

---

## Phase 8 — Live Pricing & FX Layer

- [ ] Crypto pricing (CoinGecko API)
- [ ] Stock & ETF pricing (Yahoo Finance + Stooq fallback)
- [ ] FX vrstva (EUR/CZK, USD/CZK přes ČNB)
- [ ] Cache systém (in-memory, 4h pro kurzy)
- [ ] Historické ceny assetů
- [ ] Historické FX kurzy (DB cache)

---

## Phase 9 — Budget Engine

- [ ] Měsíční rozpočty
- [ ] Limity na kategorie
- [ ] Carry-over / rollover rozpočtu
- [ ] Budget progress (spent vs. limit)
- [ ] Upozornění při překročení limitu
- [ ] Detekce přečerpání (overspending alerts)

---

## Phase 10 — Authentication & Multiuser

- [ ] Přihlášení (next-auth, email/password nebo OAuth)
- [ ] Session handling
- [ ] Registrace nových uživatelů (UI)
- [ ] Správa hesla
- [ ] Role/oprávnění (viewer, editor, owner)
- [ ] Sdílené účty (partner, rodina)
- [ ] Sdílený rozpočet

---

## Phase 11 — Product Polish

- [ ] Onboarding flow pro nové uživatele
- [ ] Loading states
- [ ] Empty states (prázdné tabulky, žádné transakce)
- [ ] Skeleton loadery
- [ ] Globální error handling
- [ ] Query optimalizace / caching
- [ ] Virtualizace dlouhých seznamů
- [ ] Lazy loading
- [ ] Mobile UX (responzivní design)
- [ ] PWA podpora

---

## Final MVP Scope

- [ ] CSV importy (Raiffeisenbank ✅, Trading212 ✅, Anycoin ✅)
- [ ] Budgeting
- [ ] Dashboard
- [ ] Portfolio overview
- [ ] Holdings
- [ ] Net worth
- [ ] Základní analytika
- [ ] Dobrá UX
