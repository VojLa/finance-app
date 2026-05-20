# Finance App — Development Roadmap & Architecture Plan

## Purpose of this document

This document defines the recommended long-term development roadmap for the finance application project.

The application combines:

- budgeting,
- transaction management,
- portfolio tracking,
- investment analytics,
- financial planning,
- and long-term net worth management

into a single platform.

The roadmap is intentionally split into phases to:

- prevent scope explosion,
- maintain architecture quality,
- allow iterative releases,
- and build a realistic MVP before scaling into a larger SaaS platform.

---

# Vision

The long-term vision is not just a budgeting application.

The goal is to build:

```text
Personal Financial Operating System
```

A unified platform where users can:

- track spending,
- manage budgets,
- monitor investments,
- analyze financial behavior,
- simulate future financial scenarios,
- and understand long-term financial outcomes.

---

# Core Product Philosophy

The application should:

- reduce manual work,
- automate repetitive actions,
- provide actionable insights,
- simplify complex financial information,
- and motivate long-term usage.

The product should focus heavily on:

```text
clarity
simplicity
automation
trust
```

---

# PHASE 0 — System Design & Architecture

## Goal

Design the architecture before large-scale development begins.

For finance applications, architecture quality is critical.

Poor architectural decisions become extremely expensive later.

---

## Estimated Time

```text
20–40 hours
```

---

# What to Design

## 1. Domain Model

Define the core entities and relationships.

### Main Entities

```text
User
Account
Transaction
InvestmentTransaction
Holding
Budget
Category
ImportBatch
ExchangeRate
```

---

## 2. Define Financial Concepts

Clearly define:

### What is a Transaction?

- expense
- income
- transfer
- loan repayment
- internal transfer

---

### What is an InvestmentTransaction?

- buy
- sell
- dividend
- staking reward
- fee
- currency conversion

---

### What is a Holding?

- current asset position
- quantity
- average buy price
- realized/unrealized P&L

---

### What is an Account?

- bank account
- broker account
- exchange account
- cash account

---

### What is an Asset?

- stock
- ETF
- crypto
- commodity
- other

---

### Currency System

Define:

- base currency,
- FX conversion strategy,
- historical exchange rates,
- multi-currency support.

---

## 3. Import Pipeline Design

This is one of the most important parts of the entire application.

### Recommended Flow

```text
CSV/API
→ parser
→ normalized rows
→ validation
→ deduplication
→ categorization
→ database insert
→ holdings recalculation
→ analytics update
```

---

# Deliverables

This phase should NOT focus on coding.

Instead produce:

- architecture diagrams,
- markdown documentation,
- entity relationship diagrams,
- module structure,
- flow diagrams,
- data flow definitions.

---

# PHASE 1 — Technical Scaffold

## Goal

Create a runnable technical foundation.

---

## Estimated Time

```text
15–30 hours
```

---

# What to Build

## Backend Foundation

### Stack

```text
Next.js 14
TypeScript
Prisma
PostgreSQL
Docker
TailwindCSS
ESLint
Prettier
```

---

## Application Structure

Recommended structure:

```text
src/
modules/
components/
lib/
types/
styles/
```

---

## Basic Routing

Create initial routes:

```text
dashboard
transactions
accounts
portfolio
settings
imports
```

---

# Important

Do NOT focus on:

- advanced design,
- animations,
- mobile apps,
- complex charts,
- advanced UX polish.

The goal is infrastructure only.

---

# PHASE 2 — Database Layer

## Goal

Create a stable and scalable financial data model.

---

## Estimated Time

```text
20–50 hours
```

---

# What to Build

## Prisma Schema

The schema must be designed carefully.

Finance applications depend heavily on data consistency.

---

## Recommended Principles

### Use Decimal instead of Float

```text
Decimal
```

should always be preferred for financial data.

---

## Use Proper Constraints

- unique indexes,
- composite keys,
- relation integrity,
- deduplication keys.

---

## Add System Tables

Example:

```text
ImportBatch
ImportLog
ExchangeRate
```

---

## Database Migrations

Set up:

- Prisma migrations,
- seed data,
- mock development data.

---

# Important

Overengineering is acceptable here.

Database mistakes become very expensive later.

---

# PHASE 3 — Accounts & Transactions

## Goal

Build the first usable version of the product.

This becomes a:

```text
mini Wallet app
```

---

## Estimated Time

```text
40–80 hours
```

---

# What to Build

## CRUD Operations

### Accounts

- create account,
- edit account,
- delete account,
- account overview.

---

### Transactions

- create transaction,
- edit transaction,
- delete transaction,
- transaction detail page,
- transaction history.

---

## Categories

### Features

- default categories,
- custom categories,
- subcategories,
- assign categories.

---

# Result

Users can:

- manage accounts,
- track expenses,
- categorize spending,
- view transaction history.

---

# PHASE 4 — Raiffeisenbank Import System

## Goal

Build the first truly valuable feature.

This is the first major product milestone.

---

## Estimated Time

```text
60–120 hours
```

Parser development always takes longer than expected.

---

# What to Build

## Upload System

### Features

- drag & drop upload,
- CSV preview,
- validation errors,
- import confirmation.

---

## Parser

The parser must handle:

- encoding issues,
- malformed rows,
- edge cases,
- formatting inconsistencies,
- missing values.

---

## Deduplication

Use:

```text
transaction ID
```

to avoid duplicates.

---

## Automatic Categorization

Examples:

```text
Tesco → Groceries
Spotify → Subscriptions
Shell → Fuel
```

---

# Result

User flow:

```text
upload CSV
→ instantly see financial overview
```

This creates the first strong product experience.

---

# PHASE 5 — Budgeting Dashboard

## Goal

Create the first real financial overview.

---

## Estimated Time

```text
40–80 hours
```

---

# What to Build

## Graphs

### Examples

- expense pie chart,
- income vs expense,
- monthly trends.

---

## Dashboard Widgets

- recent transactions,
- account balances,
- budget progress,
- net worth summary.

---

# Important

This phase introduces UX quality.

The application starts feeling like a real product.

---

# PHASE 6 — Portfolio Engine

## Goal

Transform the product from a budgeting app into a fintech platform.

This is one of the hardest parts of the entire system.

---

## Estimated Time

```text
120–250+ hours
```

Possibly significantly more.

---

# What to Build

## Investment Transaction System

Support:

- buy,
- sell,
- dividend,
- interest,
- staking,
- fees,
- currency conversion.

---

## Holdings Engine

Calculate:

- quantity,
- average buy price,
- realized P&L,
- unrealized P&L,
- allocation.

---

## Multi-Currency Support

Support:

```text
CZK
EUR
USD
```

with FX conversion.

---

## Historical Snapshots

Track:

- portfolio value over time,
- net worth history,
- historical allocations.

---

# Important

Portfolio accounting is fundamentally different from budgeting.

This phase significantly increases system complexity.

---

# PHASE 7 — Trading212 & Anycoin Imports

## Goal

Import investment transactions automatically.

---

## Estimated Time

```text
60–140 hours
```

---

# What to Build

## Trading212 Parser

Support:

- market buy,
- market sell,
- dividends,
- currency conversions,
- interest.

---

## Anycoin Pairing Logic

Pair:

```text
trade payment
+
trade fill
```

into single investment transactions.

---

## Automatic Holdings Recalculation

After each import:

```text
recalculate holdings
update analytics
refresh snapshots
```

---

# PHASE 8 — Live Pricing & FX Layer

## Goal

Provide real-time portfolio valuation.

---

## Estimated Time

```text
40–80 hours
```

---

# What to Build

## Crypto Pricing

Use:

```text
CoinGecko API
```

---

## Stock & ETF Pricing

Use:

```text
Yahoo Finance
```

---

## FX Layer

Handle:

- EUR/CZK,
- USD/CZK,
- historical rates,
- conversion caching.

---

## Cache System

Avoid excessive API calls.

---

# PHASE 9 — Budget Engine

## Goal

Build advanced budgeting functionality.

---

## Estimated Time

```text
40–70 hours
```

---

# What to Build

## Features

- monthly budgets,
- category limits,
- carry-over budgets,
- budget progress,
- alerts,
- overspending detection.

---

# PHASE 10 — Authentication & Multiuser

## Goal

Support multiple users and shared finance management.

---

## Estimated Time

```text
40–100 hours
```

---

# What to Build

## Authentication

- login,
- registration,
- session handling,
- password security.

---

## Permissions

Support:

```text
viewer
editor
owner
```

---

## Shared Accounts

Enable:

- partner accounts,
- family accounts,
- shared budgeting.

---

# PHASE 11 — Product Polish

## Goal

This phase determines long-term product success.

---

## Estimated Time

```text
100–300+ hours
```

---

# What to Improve

## UX

- onboarding,
- loading states,
- empty states,
- skeleton loaders,
- error handling.

---

## Performance

- caching,
- virtualization,
- query optimization,
- lazy loading.

---

## Mobile UX

Extremely important.

Most users will primarily use the product on mobile devices.

---

# Final MVP Scope

The MVP should include:

```text
CSV imports
budgeting
dashboard
portfolio overview
holdings
net worth
basic analytics
good UX
```

---

# Estimated Total MVP Time

## Realistic Estimate

```text
500–1000 hours
```

---

# Long-Term Vision

The final long-term platform may evolve into:

- automatic bank sync,
- broker API integrations,
- advanced financial planning,
- AI-based insights,
- predictive financial simulations,
- mobile applications,
- global SaaS infrastructure.

---

# Important Final Note

Do NOT attempt to build the final vision immediately.

The recommended strategy is:

```text
build strong foundations
→ release usable MVP
→ gather feedback
→ iterate gradually
```

The success of the product will depend more on:

```text
UX
automation
simplicity
trust
```

than on the number of features.

