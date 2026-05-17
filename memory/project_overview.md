Specifikace: Osobní finance aplikace
> Tento dokument je kompletní specifikace pro scaffold aplikace. Obsahuje vše potřebné pro vygenerování základu projektu.
---
1. O aplikaci
Webová aplikace kombinující budgeting (podobně jako Wallet app) a sledování investic (podobně jako Monero/portfolio tracker). Data se nevkládají přes live API — uživatel ručně nahrává exportované CSV soubory ze svých finančních služeb.
Zdroje dat (CSV import)
Raiffeisenbank — bankovní výpisy (výdaje, příjmy)
Trading 212 — akcie, ETF, dividendy, úroky
Anycoin — nákupy BTC (česká crypto exchange)
---
2. Tech stack
```
Frontend:     Next.js 14 (App Router, TypeScript)
Backend:      Next.js API Routes (nebo FastAPI v budoucnu)
Databáze:     PostgreSQL 16
ORM:          Prisma
Auth:         NextAuth.js (email + heslo)
Grafy:        Recharts
CSV parsing:  Papa Parse
Styling:      Tailwind CSS
Containerizace: Docker Compose
```
---
3. MVP funkce
Účty a transakce
Vytvoření účtu (typ: banka, broker, exchange, hotovost)
Ruční přidání transakce
Import CSV z Raiffeisenbank
Import CSV z Trading 212
Import CSV z Anycoin
Rozdělení transakce na více kategorií
Poznámky a přílohy k transakcím (fotka účtenky)
Rozpočty
Měsíční rozpočet po kategoriích
Upozornění při překročení rozpočtu
Přenášení nevyužitého rozpočtu do dalšího měsíce
Roční přehled rozpočtů
Kategorie
Výchozí kategorie (Jídlo, Doprava, Bydlení, Zábava, Zdraví…)
Vlastní kategorie a podkategorie
Automatická kategorizace podle klíčových slov
Ikony a barvy kategorií
Přehledy
Výdaje vs. příjmy (měsíc/rok)
Koláčový graf kategorií
Trend výdajů v čase
Čistá hodnota (net worth) v čase
Investice & Portfolio
Přidání pozice ručně (symbol, množství, nákupní cena)
Import z Trading 212 (CSV)
Import z Anycoin (CSV)
Více účtů (T212, Anycoin)
Sledování akcií, ETF, crypto
Aktuální hodnota portfolia (live ceny)
P&L na každé pozici (realized + unrealized)
Průměrná nákupní cena (DCA výpočet)
Celkový výnos v % i absolutně
Alokace portfolia (koláčový graf)
Graf vývoje hodnoty v čase
Porovnání s benchmarkem (BTC, S&P 500)
Staking / dividendy / airdrops
DCA simulátor
Kurzy
Live ceny crypto (CoinGecko API — free tier)
Live ceny akcií/ETF (Yahoo Finance)
Ruční zadání aktuální ceny
Historické ceny
Měny: CZK, EUR, USD (vše přepočítáváno do CZK jako hlavní)
Kurzy ČNB pro CZK/EUR, CZK/USD
Ostatní
Více měn + převodník (CZK, EUR, USD)
Export dat (CSV, PDF)
Synchronizace mezi zařízeními (data na serveru)
Sdílení účtu s partnerem/rodinou (role: viewer, editor, owner)
Sdílené účty (bankovní, brokerské)
NENÍ v MVP (přidat později)
❌ Opakující se transakce
❌ Cenové alerty
❌ Daňový výpis (FIFO/LIFO)
---
4. Formáty CSV souborů
4.1 Raiffeisenbank
```
Oddělovač: středník (;)
Kódování:  UTF-8
Datum:     DD.MM.YYYY nebo DD.MM.YYYY HH:MM
Čísla:     desetinná čárka, záporné = výdaj
```
Hlavička:
```
Datum provedení;Datum zaúčtování;Číslo účtu;Název účtu;Kategorie transakce;
Číslo protiúčtu;Název protiúčtu;Typ transakce;Zpráva;Poznámka;VS;KS;SS;
Zaúčtovaná částka;Měna účtu;Původní částka;Původní měna;Poplatky;
Id transakce;Vlastní poznámka;Název obchodníka;Město
```
Ukázka dat:
```csv
"15.05.2026";"15.05.2026 10:32";"1530315303/5500";"Vojtěch Lacina";"Zahraniční platba";"";"";
"Odchozí SEPA úhrada";"Odchozí SEPA úhrada";"56,23 EUR;Trading 212 Markets Limited;Vklad penez";
"";"558";"";"-56,23";"EUR";"";"";"0";"8975409009";"";"";""
```
Klíčové sloupce pro import:
Sloupec	Použití
`Datum provedení`	datum transakce
`Zaúčtovaná částka`	částka (záporná = výdaj)
`Měna účtu`	měna
`Typ transakce`	typ (Odchozí/Příchozí úhrada, SEPA...)
`Název protiúčtu`	kdo platil / komu
`Zpráva`	popis platby
`Id transakce`	unikátní ID pro deduplikaci
Poznámky:
Kategorizace se provádí na základě textu ve `Zpráva` a `Název protiúčtu`
Pole `Zpráva` může obsahovat více informací oddělených středníkem
---
4.2 Trading 212
```
Oddělovač: čárka (,)
Kódování:  UTF-8
Datum:     YYYY-MM-DD HH:MM:SS
```
Hlavička:
```
Action,Time,ISIN,Ticker,Name,Notes,ID,No. of shares,Price / share,
Currency (Price / share),Exchange rate,Result,Currency (Result),
Total,Currency (Total),Withholding tax,Currency (Withholding tax),
Currency conversion from amount,Currency (Currency conversion from amount),
Currency conversion to amount,Currency (Currency conversion to amount),
Currency conversion fee,Currency (Currency conversion fee)
```
Typy akcí (Action):
Hodnota	Popis
`Deposit`	vklad peněz na účet
`Withdrawal`	výběr z účtu
`Market buy`	nákup cenného papíru
`Market sell`	prodej cenného papíru
`Dividend (Ordinary)`	dividenda
`Dividend (Dividends paid by us corporations)`	US dividenda
`Interest on cash`	úrok na hotovost
`Currency conversion`	přepočet měny
Ukázka řádku (Market buy):
```csv
Market buy,2023-01-20 14:30:02,US0231351067,AMZN,"Amazon",,EOF2224827161,
0.2066590000,93.9200000000,USD,1.08130436,,"EUR",17.98,"EUR",,,,,,,0.03,"EUR"
```
Klíčové sloupce:
Sloupec	Použití
`Action`	typ transakce
`Time`	datum a čas
`ISIN`	identifikátor cenného papíru
`Ticker`	symbol (AMZN, TSLA...)
`Name`	název společnosti
`No. of shares`	počet akcií
`Price / share`	cena za kus
`Currency (Price / share)`	měna ceny
`Exchange rate`	kurz k EUR
`Result`	realizovaný zisk/ztráta (jen u sell)
`Total`	celková částka transakce
`Currency (Total)`	měna celkové částky
`Currency conversion fee`	poplatek za konverzi
`ID`	unikátní ID pro deduplikaci
Poznámky:
Ceny jsou typicky v USD nebo GBP, celkové částky v EUR
`Exchange rate` = kolik EUR = 1 USD (např. 1.08 = 1 USD je 1.08 EUR)
Dividendy mají `No. of shares` = množství ale `Price / share` = dividenda na akcii
`Currency conversion` má speciální sloupce pro konverzi
---
4.3 Anycoin
```
Oddělovač: čárka (,)
Kódování:  UTF-8
Datum:     ISO 8601 (YYYY-MM-DDTHH:MM:SS.mmmZ)
```
Hlavička:
```
Date,Type,Amount,Currency,Order ID,anycoin TX ID,Description
```
Typy transakcí (Type):
Hodnota	Popis
`deposit`	vklad CZK nebo BTC na účet
`trade payment`	odečtení CZK při nákupu BTC
`trade fill`	připsání BTC po nákupu
`trade refund`	vrácení CZK při neúspěšném nákupu
`withdrawal`	výběr BTC
`payment block`	dočasná blokace BTC
`payment block refund`	vrácení blokace
Ukázka párovaného nákupu (stejné Order ID):
```csv
2023-09-11T12:32:59.841Z,trade payment,-1000,CZK,1014756,3753d12e-...,
2023-09-11T12:33:15.334Z,trade fill,0.00167656,BTC,1014756,cabd72cd-...,
```
KRITICKÉ — párování nákupu:
Jeden nákup BTC = dva řádky se stejným `Order ID`:
`trade payment`: záporná částka CZK (co jsi zaplatil)
`trade fill`: kladná částka BTC (co jsi dostal)
Parser musí tyto dva řádky sloučit do jedné `InvestmentTransaction` a vypočítat průměrnou nákupní cenu:
```
avg_price_czk = abs(trade_payment.amount) / trade_fill.amount
```
---
5. Datový model (Prisma Schema)
```prisma
// schema.prisma
// Databáze: PostgreSQL 16

generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

// ─────────────────────────────────────────────
// AUTH & SDÍLENÍ
// ─────────────────────────────────────────────

model User {
  id             String          @id @default(cuid())
  email          String          @unique
  name           String?
  passwordHash   String?
  createdAt      DateTime        @default(now())
  accounts       Account[]
  budgets        Budget[]
  sharedAccounts SharedAccount[]
}

model SharedAccount {
  id          String      @id @default(cuid())
  role        SharedRole
  invitedAt   DateTime    @default(now())
  acceptedAt  DateTime?
  accountId   String
  account     Account     @relation(fields: [accountId], references: [id])
  userId      String
  user        User        @relation(fields: [userId], references: [id])

  @@unique([accountId, userId])
}

enum SharedRole {
  viewer
  editor
  owner
}

// ─────────────────────────────────────────────
// ÚČTY
// ─────────────────────────────────────────────

model Account {
  id                     String                  @id @default(cuid())
  name                   String
  type                   AccountType
  currency               String                  // primární měna účtu
  color                  String?
  icon                   String?
  userId                 String
  user                   User                    @relation(fields: [userId], references: [id])
  transactions           Transaction[]
  investmentTransactions InvestmentTransaction[]
  holdings               Holding[]
  importLogs             ImportLog[]
  sharedWith             SharedAccount[]
  createdAt              DateTime                @default(now())
}

enum AccountType {
  bank
  broker
  exchange
  cash
  crypto_wallet
}

// ─────────────────────────────────────────────
// BANKOVNÍ TRANSAKCE (z Raiffeisenbank)
// ─────────────────────────────────────────────

model Transaction {
  id             String            @id @default(cuid())
  date           DateTime
  amount         Float
  currency       String
  amountCzk      Float?            // přepočet do CZK
  type           TransactionType
  description    String?
  note           String?
  counterparty   String?           // Název protiúčtu z banky
  transactionRef String?           // Id transakce z banky — pro deduplikaci
  categoryId     String?
  category       Category?         @relation(fields: [categoryId], references: [id])
  accountId      String
  account        Account           @relation(fields: [accountId], references: [id])
  splits         TransactionSplit[]
  attachments    Attachment[]
  createdAt      DateTime          @default(now())
}

enum TransactionType {
  income
  expense
  transfer
}

model TransactionSplit {
  id            String      @id @default(cuid())
  amount        Float
  currency      String
  note          String?
  categoryId    String
  category      Category    @relation(fields: [categoryId], references: [id])
  transactionId String
  transaction   Transaction @relation(fields: [transactionId], references: [id])
}

model Attachment {
  id            String      @id @default(cuid())
  filename      String
  mimeType      String
  size          Int
  path          String
  transactionId String
  transaction   Transaction @relation(fields: [transactionId], references: [id])
  createdAt     DateTime    @default(now())
}

// ─────────────────────────────────────────────
// INVESTIČNÍ TRANSAKCE (Trading 212 + Anycoin)
// ─────────────────────────────────────────────

model InvestmentTransaction {
  id            String         @id @default(cuid())
  date          DateTime
  type          InvestmentType

  // Cenný papír / krypto
  symbol        String?        // TSLA, BTC, VUAA
  isin          String?
  name          String?
  assetType     AssetType?

  // Množství a cena
  quantity      Float?
  pricePerUnit  Float?
  priceCurrency String?

  // Výsledek transakce
  totalAmount   Float?
  totalCurrency String?

  // Poplatky
  fee           Float?
  feeCurrency   String?

  // Devizový kurz (z T212: Price/EUR)
  exchangeRate  Float?

  // Párování (Anycoin: Order ID)
  orderId       String?

  // Deduplikace (ID z burzy)
  externalId    String?

  // Zisk/ztráta (u prodeje)
  realizedPnl      Float?
  realizedPnlCurrency String?

  accountId     String
  account       Account @relation(fields: [accountId], references: [id])
  createdAt     DateTime @default(now())
}

enum InvestmentType {
  buy
  sell
  deposit
  withdrawal
  dividend
  interest
  currency_conversion
  staking_reward
  airdrop
  fee
}

enum AssetType {
  stock
  etf
  crypto
  commodity
  other
}

// ─────────────────────────────────────────────
// PORTFOLIO — AKTUÁLNÍ POZICE
// ─────────────────────────────────────────────

model Holding {
  id           String    @id @default(cuid())
  symbol       String
  name         String?
  assetType    AssetType
  quantity     Float
  avgBuyPrice  Float     // DCA průměrná nákupní cena
  currency     String    // měna nákupní ceny
  accountId    String
  account      Account   @relation(fields: [accountId], references: [id])
  updatedAt    DateTime  @updatedAt

  @@unique([symbol, accountId])
}

// ─────────────────────────────────────────────
// KATEGORIE
// ─────────────────────────────────────────────

model Category {
  id           String            @id @default(cuid())
  name         String
  icon         String?
  color        String?
  type         CategoryType
  parentId     String?
  parent       Category?         @relation("Subcategories", fields: [parentId], references: [id])
  children     Category[]        @relation("Subcategories")
  isDefault    Boolean           @default(false)
  transactions Transaction[]
  splits       TransactionSplit[]
  budgetItems  BudgetItem[]
  rules        CategoryRule[]
}

enum CategoryType {
  expense
  income
  both
}

model CategoryRule {
  id         String   @id @default(cuid())
  keyword    String   // "Tesco", "Netflix", "Albert"
  field      RuleField
  priority   Int      @default(0)
  categoryId String
  category   Category @relation(fields: [categoryId], references: [id])
}

enum RuleField {
  description
  counterparty
}

// ─────────────────────────────────────────────
// ROZPOČTY
// ─────────────────────────────────────────────

model Budget {
  id        String       @id @default(cuid())
  month     Int          // 1–12
  year      Int
  rollover  Boolean      @default(false)
  userId    String
  user      User         @relation(fields: [userId], references: [id])
  items     BudgetItem[]
  createdAt DateTime     @default(now())

  @@unique([month, year, userId])
}

model BudgetItem {
  id             String   @id @default(cuid())
  amount         Float    // limit
  spent          Float    @default(0)
  currency       String   @default("CZK")
  rolloverAmount Float?   // přeneseno z předchozího měsíce
  budgetId       String
  budget         Budget   @relation(fields: [budgetId], references: [id])
  categoryId     String
  category       Category @relation(fields: [categoryId], references: [id])
}

// ─────────────────────────────────────────────
// KURZY MĚN
// ─────────────────────────────────────────────

model ExchangeRate {
  id           String   @id @default(cuid())
  fromCurrency String
  toCurrency   String
  rate         Float
  date         DateTime
  source       RateSource

  @@unique([fromCurrency, toCurrency, date])
}

enum RateSource {
  cnb      // Česká národní banka
  ecb      // Evropská centrální banka
  manual   // Ruční zadání
}

// ─────────────────────────────────────────────
// SYSTÉM — IMPORT LOGY
// ─────────────────────────────────────────────

model ImportLog {
  id           String       @id @default(cuid())
  filename     String
  source       ImportSource
  rowsImported Int
  rowsSkipped  Int
  accountId    String
  account      Account      @relation(fields: [accountId], references: [id])
  importedAt   DateTime     @default(now())
}

enum ImportSource {
  raiffeisenbank
  trading212
  anycoin
  manual
}
```
---
6. Struktura projektu
```
finance-app/
├── docker-compose.yml
├── .env.example
├── prisma/
│   ├── schema.prisma           ← viz sekce 5
│   └── seed.ts                 ← výchozí kategorie
│
├── src/
│   ├── app/                    ← Next.js App Router
│   │   ├── layout.tsx
│   │   ├── page.tsx            ← redirect na /dashboard
│   │   │
│   │   ├── (auth)/
│   │   │   ├── login/page.tsx
│   │   │   └── register/page.tsx
│   │   │
│   │   ├── dashboard/page.tsx  ← přehled (net worth, výdaje, portfolio)
│   │   ├── transactions/
│   │   │   ├── page.tsx        ← seznam transakcí
│   │   │   └── [id]/page.tsx   ← detail transakce
│   │   ├── budget/page.tsx     ← měsíční rozpočty
│   │   ├── portfolio/
│   │   │   ├── page.tsx        ← přehled portfolia
│   │   │   └── [symbol]/page.tsx ← detail pozice
│   │   ├── import/page.tsx     ← nahrání CSV souboru
│   │   ├── accounts/page.tsx   ← správa účtů
│   │   └── settings/page.tsx   ← kategorie, pravidla, profil
│   │
│   ├── api/                    ← Next.js API Routes
│   │   ├── auth/[...nextauth]/route.ts
│   │   ├── transactions/route.ts
│   │   ├── import/
│   │   │   ├── raiffeisenbank/route.ts
│   │   │   ├── trading212/route.ts
│   │   │   └── anycoin/route.ts
│   │   ├── portfolio/route.ts
│   │   ├── budget/route.ts
│   │   └── rates/route.ts      ← kurzy měn
│   │
│   ├── lib/
│   │   ├── prisma.ts           ← Prisma client singleton
│   │   ├── auth.ts             ← NextAuth config
│   │   └── rates.ts            ← CoinGecko + Yahoo Finance fetch
│   │
│   ├── parsers/                ← CSV parsery pro každý zdroj
│   │   ├── raiffeisenbank.ts
│   │   ├── trading212.ts
│   │   └── anycoin.ts
│   │
│   ├── components/
│   │   ├── ui/                 ← základní komponenty (Button, Card, Input...)
│   │   ├── charts/             ← Recharts wrappery
│   │   ├── transactions/
│   │   ├── portfolio/
│   │   └── budget/
│   │
│   └── types/
│       └── index.ts            ← sdílené TypeScript typy
│
└── public/
```
---
7. Výchozí kategorie (seed data)
```typescript
// prisma/seed.ts — výchozí kategorie pro nové uživatele

const defaultCategories = [
  // Výdaje
  { name: "Jídlo & Restaurace", icon: "🍽️", color: "#ef4444", type: "expense" },
  { name: "Potraviny", icon: "🛒", color: "#f97316", type: "expense", parent: "Jídlo & Restaurace" },
  { name: "Restaurace & Kavárny", icon: "☕", color: "#f59e0b", type: "expense", parent: "Jídlo & Restaurace" },
  
  { name: "Doprava", icon: "🚗", color: "#3b82f6", type: "expense" },
  { name: "Pohonné hmoty", icon: "⛽", color: "#2563eb", type: "expense", parent: "Doprava" },
  { name: "Veřejná doprava", icon: "🚌", color: "#1d4ed8", type: "expense", parent: "Doprava" },
  
  { name: "Bydlení", icon: "🏠", color: "#8b5cf6", type: "expense" },
  { name: "Nájem", icon: "🔑", color: "#7c3aed", type: "expense", parent: "Bydlení" },
  { name: "Energie & Voda", icon: "💡", color: "#6d28d9", type: "expense", parent: "Bydlení" },
  
  { name: "Zdraví", icon: "💊", color: "#10b981", type: "expense" },
  { name: "Léky", icon: "💉", color: "#059669", type: "expense", parent: "Zdraví" },
  { name: "Lékař", icon: "🏥", color: "#047857", type: "expense", parent: "Zdraví" },
  
  { name: "Zábava", icon: "🎮", color: "#ec4899", type: "expense" },
  { name: "Předplatné", icon: "📺", color: "#db2777", type: "expense", parent: "Zábava" },
  { name: "Sport", icon: "🏋️", color: "#be185d", type: "expense", parent: "Zábava" },
  
  { name: "Oblečení", icon: "👕", color: "#f59e0b", type: "expense" },
  { name: "Elektronika", icon: "💻", color: "#6366f1", type: "expense" },
  { name: "Vzdělání", icon: "📚", color: "#0891b2", type: "expense" },
  { name: "Investice", icon: "📈", color: "#16a34a", type: "expense" },
  { name: "Ostatní výdaje", icon: "💸", color: "#64748b", type: "expense" },
  
  // Příjmy
  { name: "Výplata", icon: "💼", color: "#22c55e", type: "income" },
  { name: "Freelance", icon: "🖥️", color: "#16a34a", type: "income" },
  { name: "Dividendy", icon: "🏦", color: "#15803d", type: "income" },
  { name: "Ostatní příjmy", icon: "💰", color: "#4ade80", type: "income" },
]
```
---
8. Klíčová logika parserů
8.1 Raiffeisenbank parser
```typescript
// src/parsers/raiffeisenbank.ts
import Papa from "papaparse"
import { TransactionType } from "@prisma/client"

const INCOME_TYPES = ["Příchozí úhrada", "Příchozí SEPA úhrada", "Příchozí platba"]
const EXPENSE_TYPES = ["Odchozí úhrada", "Odchozí SEPA úhrada", "Platba kartou"]

export function parseRaiffeisenbank(csvText: string, accountId: string) {
  const result = Papa.parse(csvText, {
    delimiter: ";",
    header: true,
    encoding: "UTF-8",
    skipEmptyLines: true,
  })

  return result.data.map((row: any) => {
    const amount = parseFloat(row["Zaúčtovaná částka"].replace(",", "."))
    const typText = row["Typ transakce"]
    
    let type: TransactionType = "expense"
    if (INCOME_TYPES.some(t => typText.includes(t))) type = "income"
    if (amount > 0) type = "income"

    return {
      date: parseDate(row["Datum provedení"]),
      amount: Math.abs(amount),
      currency: row["Měna účtu"],
      type,
      description: row["Zpráva"] || row["Poznámka"] || "",
      counterparty: row["Název protiúčtu"] || "",
      transactionRef: row["Id transakce"],
      accountId,
    }
  })
}

function parseDate(str: string): Date {
  // "15.05.2026" nebo "15.05.2026 10:32"
  const [datePart] = str.split(" ")
  const [d, m, y] = datePart.split(".")
  return new Date(`${y}-${m}-${d}`)
}
```
8.2 Anycoin parser — párování nákupů
```typescript
// src/parsers/anycoin.ts
import Papa from "papaparse"

export function parseAnycoin(csvText: string, accountId: string) {
  const result = Papa.parse(csvText, {
    header: true,
    skipEmptyLines: true,
  })

  const rows = result.data as any[]
  
  // Skupinování trade payment + trade fill podle Order ID
  const orders: Record<string, { payment?: any; fill?: any }> = {}
  const standalone: any[] = []

  for (const row of rows) {
    const type = row["Type"]
    const orderId = row["Order ID"]

    if (type === "trade payment" && orderId) {
      if (!orders[orderId]) orders[orderId] = {}
      orders[orderId].payment = row
    } else if (type === "trade fill" && orderId) {
      if (!orders[orderId]) orders[orderId] = {}
      orders[orderId].fill = row
    } else if (type === "trade refund") {
      // přeskočit — zrušený nákup
    } else {
      standalone.push(row)
    }
  }

  const transactions = []

  // Zpracovat párované nákupy
  for (const [orderId, order] of Object.entries(orders)) {
    if (order.payment && order.fill) {
      const paidCzk = Math.abs(parseFloat(order.payment["Amount"]))
      const receivedBtc = parseFloat(order.fill["Amount"])
      const avgPriceCzk = paidCzk / receivedBtc

      transactions.push({
        date: new Date(order.fill["Date"]),
        type: "buy",
        symbol: order.fill["Currency"],  // BTC
        assetType: "crypto",
        quantity: receivedBtc,
        pricePerUnit: avgPriceCzk,
        priceCurrency: order.payment["Currency"],  // CZK
        totalAmount: paidCzk,
        totalCurrency: "CZK",
        orderId,
        externalId: order.fill["anycoin TX ID"],
        accountId,
      })
    }
  }

  // Zpracovat standalone transakce (deposit, withdrawal)
  for (const row of standalone) {
    const type = row["Type"]
    if (type === "deposit") {
      transactions.push({
        date: new Date(row["Date"]),
        type: "deposit",
        totalAmount: parseFloat(row["Amount"]),
        totalCurrency: row["Currency"],
        externalId: row["anycoin TX ID"],
        accountId,
      })
    } else if (type === "withdrawal") {
      transactions.push({
        date: new Date(row["Date"]),
        type: "withdrawal",
        quantity: Math.abs(parseFloat(row["Amount"])),
        symbol: row["Currency"],
        externalId: row["anycoin TX ID"],
        accountId,
      })
    }
  }

  return transactions
}
```
8.3 Trading 212 parser
```typescript
// src/parsers/trading212.ts
import Papa from "papaparse"

const ACTION_MAP: Record<string, string> = {
  "Market buy": "buy",
  "Market sell": "sell",
  "Deposit": "deposit",
  "Withdrawal": "withdrawal",
  "Dividend (Ordinary)": "dividend",
  "Dividend (Dividends paid by us corporations)": "dividend",
  "Interest on cash": "interest",
  "Currency conversion": "currency_conversion",
}

export function parseTrading212(csvText: string, accountId: string) {
  const result = Papa.parse(csvText, {
    header: true,
    skipEmptyLines: true,
  })

  return result.data
    .map((row: any) => {
      const action = row["Action"]
      const type = ACTION_MAP[action]
      if (!type) return null

      return {
        date: new Date(row["Time"]),
        type,
        symbol: row["Ticker"] || null,
        isin: row["ISIN"] || null,
        name: row["Name"] || null,
        assetType: detectAssetType(row["ISIN"], row["Ticker"]),
        quantity: row["No. of shares"] ? parseFloat(row["No. of shares"]) : null,
        pricePerUnit: row["Price / share"] ? parseFloat(row["Price / share"]) : null,
        priceCurrency: row["Currency (Price / share)"] || null,
        exchangeRate: row["Exchange rate"] ? parseFloat(row["Exchange rate"]) : null,
        totalAmount: row["Total"] ? parseFloat(row["Total"]) : null,
        totalCurrency: row["Currency (Total)"] || null,
        fee: row["Currency conversion fee"] ? parseFloat(row["Currency conversion fee"]) : null,
        feeCurrency: row["Currency (Currency conversion fee)"] || null,
        realizedPnl: row["Result"] ? parseFloat(row["Result"]) : null,
        realizedPnlCurrency: row["Currency (Result)"] || null,
        externalId: row["ID"] || null,
        accountId,
      }
    })
    .filter(Boolean)
}

function detectAssetType(isin: string, ticker: string): string {
  // ETF identifikace podle ISIN prefix (IE = Irsko = většina ETF)
  if (isin?.startsWith("IE")) return "etf"
  return "stock"
}
```
---
9. Výpočet DCA (průměrná nákupní cena)
```typescript
// src/lib/portfolio.ts

// Přepočet holdings ze všech InvestmentTransaction pro daný účet
export async function recalculateHoldings(accountId: string) {
  const buyTransactions = await prisma.investmentTransaction.findMany({
    where: { accountId, type: "buy" },
    orderBy: { date: "asc" },
  })
  const sellTransactions = await prisma.investmentTransaction.findMany({
    where: { accountId, type: "sell" },
    orderBy: { date: "asc" },
  })

  const positions: Record<string, { quantity: number; totalCost: number; currency: string }> = {}

  for (const tx of buyTransactions) {
    if (!tx.symbol) continue
    if (!positions[tx.symbol]) positions[tx.symbol] = { quantity: 0, totalCost: 0, currency: tx.priceCurrency || "EUR" }
    positions[tx.symbol].quantity += tx.quantity || 0
    positions[tx.symbol].totalCost += (tx.quantity || 0) * (tx.pricePerUnit || 0)
  }

  for (const tx of sellTransactions) {
    if (!tx.symbol || !positions[tx.symbol]) continue
    positions[tx.symbol].quantity -= tx.quantity || 0
    // FIFO by se řešil komplexněji — pro MVP stačí průměr
    const avgPrice = positions[tx.symbol].totalCost / (positions[tx.symbol].quantity + (tx.quantity || 0))
    positions[tx.symbol].totalCost -= (tx.quantity || 0) * avgPrice
  }

  // Upsert do Holding tabulky
  for (const [symbol, pos] of Object.entries(positions)) {
    if (pos.quantity <= 0) continue
    await prisma.holding.upsert({
      where: { symbol_accountId: { symbol, accountId } },
      update: {
        quantity: pos.quantity,
        avgBuyPrice: pos.totalCost / pos.quantity,
        currency: pos.currency,
      },
      create: {
        symbol,
        quantity: pos.quantity,
        avgBuyPrice: pos.totalCost / pos.quantity,
        currency: pos.currency,
        assetType: "stock", // aktualizovat dle dat
        accountId,
      },
    })
  }
}
```
---
10. Live kurzy — API integrace
CoinGecko (crypto — free tier)
```
GET https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=czk,eur,usd
```
Yahoo Finance (akcie/ETF)
```
Knihovna: yahoo-finance2 (npm)
import yahooFinance from "yahoo-finance2"
const quote = await yahooFinance.quote("TSLA")
// quote.regularMarketPrice — aktuální cena v USD
```
ČNB kurzy (CZK/EUR, CZK/USD)
```
GET https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt
```
---
11. Docker Compose
```yaml
# docker-compose.yml
version: "3.9"

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: finance_app
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  app:
    build: .
    ports:
      - "3000:3000"
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/finance_app
      NEXTAUTH_SECRET: your-secret-here
      NEXTAUTH_URL: http://localhost:3000
    depends_on:
      - db
    volumes:
      - ./:/app
      - /app/node_modules

volumes:
  postgres_data:
```
---
12. Environment proměnné
```env
# .env.example

# Databáze
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/finance_app"

# Auth
NEXTAUTH_SECRET="your-secret-min-32-chars"
NEXTAUTH_URL="http://localhost:3000"

# Kurzy (volitelné — free tier nepotřebuje klíč)
COINGECKO_API_KEY=""
YAHOO_FINANCE_ENABLED="true"

# ČNB kurzy
CNB_RATES_URL="https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt"
```
---
13. Priorita implementace
Základ — Next.js scaffold, Prisma, Docker, NextAuth
Účty — CRUD účtů (banka, broker, exchange)
Import RB — parser + zobrazení transakcí
Kategorie — výchozí sada + přiřazení k transakcím
Import T212 — parser + zobrazení portfolia
Import Anycoin — parser + párování order ID
Portfolio přehled — holdings, P&L, live ceny
Rozpočty — měsíční limit, čerpání
Dashboard — net worth, výdaje, portfolio summary
Kurzy měn — CoinGecko, Yahoo Finance, ČNB
Grafy — Recharts komponenty
Export — CSV, PDF
Sdílení — SharedAccount, role
```