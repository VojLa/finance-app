# Finance App — Domain Model

## Purpose of this document

This document defines the domain model for a personal finance application that combines budgeting, cashflow tracking, investment tracking, portfolio analytics, and long-term financial planning.

This document intentionally does not define:

- database schema,
- Prisma models,
- API routes,
- UI components,
- implementation details,
- technical stack decisions.

The purpose is to define the financial concepts, relationships, and behavioral rules that should guide later implementation.

---

# 1. Core Domain Philosophy

The application has two major financial domains:

```text
1. Personal Cashflow Domain
   → accounts, income, expenses, transfers, categories, budgets

2. Investment Portfolio Domain
   → assets, trades, dividends, holdings, prices, performance
```

These two domains are separate, but they connect through one shared aggregate:

```text
Net Worth
```

Net worth combines:

```text
bank account balances
+ cash balances
+ broker cash
+ investment holdings
+ crypto holdings
- debts and liabilities
= total personal wealth
```

The most important design principle is:

```text
Not every money movement is real income or real expense.
```

Examples of money movements that should not distort budgeting:

- transfers between own accounts,
- broker deposits,
- crypto exchange deposits,
- ATM withdrawals,
- family loans,
- repayments,
- cash exchanges,
- credit card repayments.

The app must understand these distinctions to avoid misleading analytics.

---

# 2. Main Domain Entities

The domain model contains the following main entities:

```text
User
Account
Transaction
TransactionSplit
TransactionClassification
TransactionReview
Counterparty
Category
CategoryRule
Budget
BudgetItem
Asset
InvestmentTransaction
Holding
PriceSnapshot
ExchangeRate
ImportBatch
ImportRow
NetWorthSnapshot
FinancialGoal
ForecastScenario
```

---

# 3. User

## Meaning

A `User` represents the owner of financial data.

## Responsibilities

A user owns:

```text
accounts
transactions
categories
budgets
assets
investment transactions
imports
goals
settings
```

## Important attributes

```text
id
email
name
baseCurrency
createdAt
```

## Important rule

Every user should have a `baseCurrency`.

Examples:

```text
CZK
EUR
USD
```

The base currency is used for:

- dashboard summaries,
- net worth calculation,
- charts,
- budget overview,
- forecasting,
- long-term planning.

---

# 4. Account

## Meaning

An `Account` represents a place where money, assets, or liabilities are held.

Examples:

```text
checking account
savings account
cash wallet
broker account
crypto exchange account
crypto wallet
credit card
loan
mortgage
```

## Account types

```text
bank
cash
savings
broker
exchange
crypto_wallet
credit_card
loan
mortgage
```

## Responsibilities

An account can contain:

```text
cashflow transactions
investment transactions
holdings
balances
```

## Important attributes

```text
id
user_id
name
type
currency
initialBalance
currentBalance
isArchived
createdAt
```

## Important rule

Not all accounts behave the same way.

A bank account is primarily used for:

```text
cashflow tracking
```

A broker account is primarily used for:

```text
portfolio tracking
```

A loan account is primarily used for:

```text
liability tracking
```

However, all account types may contribute to:

```text
net worth
```

---

# 5. Transaction

## Meaning

A `Transaction` represents a money movement in the personal cashflow domain.

Examples:

```text
grocery purchase
salary payment
rent payment
fuel payment
restaurant payment
subscription payment
transfer between own accounts
loan to a friend
repayment from a family member
broker deposit
ATM withdrawal
```

## Basic transaction types

```text
income
expense
transfer_income
transfer_expense
```

## Extended future transaction types

```text
loan_given
loan_received
loan_repayment
refund
cash_deposit
cash_withdrawal
investment_transfer
adjustment
ignored
```

## Important attributes

```text
id
userId
accountId
date
amount
currency
amountInBaseCurrency
type
classification
categoryId
counterpartyId
description
externalId
importBatchId
createdAt
```

## Important rule

A bank transaction is not automatically a budget expense or budget income.

Examples:

```text
transfer between own accounts
broker deposit
ATM withdrawal
family loan
loan repayment
```

These transactions should not distort budgeting statistics.

---

# 6. TransactionClassification

## Meaning

`TransactionClassification` defines how a transaction behaves in analytics.

This is different from category.

Category answers:

```text
What was this transaction about?
```

Classification answers:

```text
How should this transaction be counted?
```

## Suggested classification values

```text
real_income
real_expense
internal_transfer
investment_transfer
loan_given
loan_received
loan_repayment
refund
cash_exchange
credit_card_payment
ignored
needs_review
```

## Example 1 — Trading 212 deposit

```text
Category: Investments
Classification: investment_transfer
Budget impact: excluded from normal spending
Net worth impact: neutral
```

## Example 2 — grocery purchase

```text
Category: Groceries
Classification: real_expense
Budget impact: included
Net worth impact: decreases cash
```

## Example 3 — salary payment

```text
Category: Salary
Classification: real_income
Budget impact: included as income
Net worth impact: increases cash
```

## Important rule

Classification should drive analytics behavior.

Category should drive human-readable grouping.

---

# 7. InternalTransfer

## Meaning

An `InternalTransfer` is a money movement between accounts that belong to the same user.

Examples:

```text
checking account → savings account
checking account → broker account
checking account → Revolut account
checking account → cash wallet
CZK account → EUR account
```

## Problem

Without transfer detection, the app shows fake income and fake expenses.

Example:

```text
The user transfers 10,000 CZK from a bank account to Revolut.
```

Incorrect interpretation:

```text
Expense: 10,000 CZK
Income: 10,000 CZK
```

Correct interpretation:

```text
Internal transfer
Budget impact: 0 CZK
Net worth impact: 0 CZK
```

## Recommended behavior

The system should detect transfers by comparing:

```text
amount
date
opposite direction
currency
known accounts
account numbers
transaction descriptions
```

## Important rule

Transfers should be excluded from normal spending and income charts by default.

---

# 8. Counterparty

## Meaning

A `Counterparty` represents the other side of a transaction.

Examples:

```text
merchant
family member
partner
friend
employer
broker
crypto exchange
bank
service provider
company
```

## Why it matters

Counterparties help the app understand transaction meaning.

Example:

```text
Payment to father's bank account detected.
```

The app can ask:

```text
What was this transaction?

- loan to family
- debt repayment
- shared expense
- gift
- cash exchange
- ignore from budget
```

## Counterparty types

```text
merchant
family
partner
friend
employer
broker
exchange
bank
service_provider
other
```

## Important attributes

```text
id
userId
name
type
accountNumber
iban
notes
createdAt
```

## Important rule

Known counterparties should improve automation and reduce manual categorization.

---

# 9. TransactionReview

## Meaning

`TransactionReview` represents a transaction that requires user clarification.

The app should not silently make uncertain financial decisions.

## When it is created

A review item may be created when the app detects:

```text
large unusual transaction
payment to family account
possible internal transfer
payment to broker
unknown counterparty
duplicate-like transaction
uncertain category
uncertain classification
```

## Purpose

Instead of making a wrong assumption, the app asks the user to clarify the transaction.

## Example flow

```text
The app found 4 transactions that need review.
```

The user quickly decides:

```text
This is a transfer.
This is a loan.
This is a real expense.
Always classify this merchant as groceries.
```

## Important attributes

```text
id
transactionId
reason
suggestedClassification
suggestedCategoryId
status
resolvedAt
createdAt
```

## Important rule

The review queue is a key UX feature.

It keeps financial data accurate without forcing the user to manually inspect every transaction.

---

# 10. Category

## Meaning

A `Category` describes what a transaction is about.

Examples:

```text
Groceries
Restaurants
Housing
Transport
Healthcare
Entertainment
Subscriptions
Investments
Salary
Dividends
Other
```

## Category types

```text
income
expense
both
```

## Category hierarchy

Categories can have subcategories.

Example:

```text
Food
├── Groceries
├── Restaurants
└── Cafes
```

## Important attributes

```text
id
userId
name
parentId
type
icon
color
isDefault
createdAt
```

## Important rule

Category is not the same as classification.

Example:

```text
Category: Investments
Classification: investment_transfer
```

This means:

```text
The transaction is related to investments.
It is not a normal living expense.
```

---

# 11. CategoryRule

## Meaning

A `CategoryRule` automatically assigns categories or classifications to transactions.

## Examples

```text
Description contains "Tesco" → Category: Groceries
Description contains "Spotify" → Category: Subscriptions
Counterparty is "Trading 212" → Classification: investment_transfer
Counterparty is "Anycoin" → Classification: investment_transfer
Counterparty is family account → Classification: needs_review
```

## A rule can assign

```text
category
classification
review requirement
priority
```

## Important attributes

```text
id
userId
field
operator
value
categoryId
classification
priority
createdAt
```

## Important rule

Automation rules are essential for retention.

If users must constantly repair categories manually, they will eventually stop using the app.

---

# 12. TransactionSplit

## Meaning

A `TransactionSplit` allows one transaction to be split into multiple parts.

## Example

A supermarket transaction of 1,200 CZK:

```text
800 CZK → Groceries
250 CZK → Drugstore
150 CZK → Household
```

## Important attributes

```text
id
transactionId
amount
currency
categoryId
note
```

## Important rule

Splits are useful, but they are not required for the earliest MVP.

They should be supported by the domain model because they are common in real personal finance tracking.

---

# 13. Budget

## Meaning

A `Budget` represents a spending plan for a defined period.

Most commonly, the period is monthly.

## Example

```text
Budget for May 2026
```

A budget contains multiple category limits.

## Period types

For MVP:

```text
monthly
```

Future options:

```text
weekly
yearly
custom
```

## Important attributes

```text
id
userId
periodType
month
year
currency
rolloverEnabled
createdAt
```

---

# 14. BudgetItem

## Meaning

A `BudgetItem` defines the spending limit for one category within a budget.

## Examples

```text
Groceries: 8,000 CZK
Restaurants: 3,000 CZK
Transport: 4,000 CZK
Entertainment: 2,000 CZK
```

## Important attributes

```text
id
budgetId
categoryId
limitAmount
currency
rolloverAmount
createdAt
```

## Important rule

Spent amount should ideally be calculated from transactions.

It should not be treated as the primary source of truth.

A stored spent amount can exist only as a cached analytics value.

---

# 15. Asset

## Meaning

An `Asset` represents an investable item.

Examples:

```text
Apple stock
Tesla stock
VUAA ETF
VWCE ETF
Bitcoin
Ethereum
EUR cash
USD cash
Gold
```

## Asset types

```text
stock
etf
crypto
commodity
cash
bond
other
```

## Important attributes

```text
id
symbol
isin
name
assetType
currency
providerId
createdAt
```

## Example

```text
Symbol: VUAA
ISIN: IE00BFMXXD54
Name: Vanguard S&P 500 UCITS ETF
Asset type: ETF
Currency: EUR
```

---

# 16. InvestmentTransaction

## Meaning

An `InvestmentTransaction` represents an investment-related event.

Examples:

```text
buy ETF
sell stock
receive dividend
receive interest
receive staking reward
pay broker fee
currency conversion
buy BTC
crypto withdrawal
broker deposit
```

## Types

```text
buy
sell
dividend
interest
deposit
withdrawal
fee
currency_conversion
staking_reward
airdrop
transfer
```

## Important attributes

```text
id
userId
accountId
assetId
date
type
quantity
pricePerUnit
priceCurrency
totalAmount
totalCurrency
fee
feeCurrency
exchangeRate
externalId
importBatchId
createdAt
```

## Important rule

A broker deposit is not the same as buying an asset.

Example:

```text
Bank account → Trading 212
```

This is:

```text
investment transfer / broker deposit
```

Not:

```text
buy transaction
```

The actual asset purchase happens later inside the broker account.

---

# 17. Holding

## Meaning

A `Holding` represents the current position in an asset.

Examples:

```text
VUAA: 12.5 shares
BTC: 0.05 BTC
Apple: 4 shares
```

## Important principle

Holding is derived state.

The source of truth should be:

```text
InvestmentTransaction
```

The derived current state is:

```text
Holding
```

## Holding calculations

A holding can calculate:

```text
quantity
average buy price
current price
current value
unrealized P&L
realized P&L
allocation
```

## Important attributes

```text
id
userId
accountId
assetId
quantity
averageBuyPrice
averageBuyPriceCurrency
currentPrice
currentValue
unrealizedPnl
realizedPnl
updatedAt
```

## Important rule

If investment transactions are recalculated, holdings should be recalculated too.

---

# 18. PriceSnapshot

## Meaning

A `PriceSnapshot` stores the market price of an asset at a point in time.

## Used for

```text
current portfolio value
historical portfolio charts
unrealized P&L
benchmark comparison
net worth history
```

## Important attributes

```text
id
assetId
price
currency
source
timestamp
createdAt
```

## Example

```text
Asset: BTC
Price: 2,500,000 CZK
Timestamp: 2026-05-20
Source: CoinGecko
```

---

# 19. ExchangeRate

## Meaning

An `ExchangeRate` stores the conversion rate between two currencies.

## Examples

```text
EUR → CZK
USD → CZK
USD → EUR
BTC → CZK
```

## Used for

```text
transaction conversion into base currency
investment conversion
historical charts
net worth calculation
forecasting
```

## Important attributes

```text
id
fromCurrency
toCurrency
rate
date
source
createdAt
```

## Important rule

Historical transactions should use historical exchange rates when possible.

Current dashboard values can use the latest available rates.

---

# 20. ImportBatch

## Meaning

An `ImportBatch` represents one import operation.

It can be:

```text
bank CSV file
broker CSV file
crypto exchange CSV file
future bank API sync
future broker API sync
```

## Why it matters

ImportBatch enables:

```text
preventing duplicate imports
showing import history
rolling back imports in the future
debugging failed rows
tracking data source
```

## Examples

```text
Raiffeisenbank CSV — May 2026
Trading 212 export — 2024–2026
Anycoin export — BTC purchases
```

## Important attributes

```text
id
userId
accountId
source
filename
checksum
status
rowsTotal
rowsImported
rowsSkipped
createdAt
completedAt
```

---

# 21. ImportRow

## Meaning

An `ImportRow` represents one row from an imported file or API sync result.

## Contains

```text
raw data
normalized data
status
error message
created transaction reference
created investment transaction reference
```

## Why it matters

ImportRow helps with:

```text
parser errors
invalid rows
duplicate rows
user corrections
future import improvements
```

## Important attributes

```text
id
importBatchId
rowNumber
rawData
normalizedData
status
errorMessage
createdTransactionId
createdInvestmentTransactionId
createdAt
```

---

# 22. FinancialGoal

## Meaning

A `FinancialGoal` represents a future financial target.

Examples:

```text
buy a car
buy a house
vacation
emergency fund
pay off debt
reach portfolio target value
mortgage down payment
```

## Goal types

```text
saving
purchase
debt_payoff
investment_target
emergency_fund
custom
```

## Important attributes

```text
id
userId
name
type
targetAmount
currency
targetDate
currentAmount
priority
createdAt
```

## Example

```text
Goal: Buy a car
Target amount: 300,000 CZK
Target date: 2027
Priority: high
```

---

# 23. ForecastScenario

## Meaning

A `ForecastScenario` is used to simulate possible financial futures.

## Example questions

```text
How much money can I have in 5 years?
What happens if I buy a car for 250,000 CZK?
What is the impact of a mortgage?
How much can I invest monthly?
When can I reach 1,000,000 CZK net worth?
```

## Important attributes

```text
id
userId
name
assumptions
result
createdAt
```

## Important rule

Forecasting should not be presented as certainty.

It should be presented as scenario-based planning.

---

# 24. NetWorthSnapshot

## Meaning

A `NetWorthSnapshot` stores the user's total wealth at a specific point in time.

## Contains

```text
cash value
bank account value
broker cash value
portfolio value
crypto value
debts
total net worth
currency
date
```

## Why it matters

Without snapshots, it is difficult to show historical net worth development.

Example chart:

```text
January: 250,000 CZK
February: 267,000 CZK
March: 281,000 CZK
April: 275,000 CZK
May: 310,000 CZK
```

## Important rule

Net worth should be treated as an aggregate view.

It is computed from accounts, holdings, prices, exchange rates, and liabilities.

---

# 25. Core Relationships

## User → Account

```text
User has many Accounts
Account belongs to one User
```

## Account → Transaction

```text
Account has many Transactions
Transaction belongs to one Account
```

## Account → InvestmentTransaction

```text
Broker or exchange Account has many InvestmentTransactions
InvestmentTransaction belongs to one Account
```

## InvestmentTransaction → Asset

```text
InvestmentTransaction may reference one Asset
Asset can have many InvestmentTransactions
```

## Asset → Holding

```text
Holding represents the current ownership of an Asset in a specific Account
```

## Transaction → Category

```text
Transaction may have one Category
Category can have many Transactions
```

## Transaction → TransactionSplit

```text
Transaction can have many TransactionSplits
TransactionSplit belongs to one Transaction
```

## Budget → BudgetItem

```text
Budget has many BudgetItems
BudgetItem belongs to one Category
```

## ImportBatch → ImportRow

```text
ImportBatch has many ImportRows
ImportRow may create a Transaction or InvestmentTransaction
```

## User → FinancialGoal

```text
User has many FinancialGoals
FinancialGoal belongs to one User
```

## FinancialGoal → ForecastScenario

```text
ForecastScenario can be based on one or more FinancialGoals
```

---

# 26. Core Domain Rules

## Rule 1 — Not every bank transaction is an expense

Examples:

```text
transfer to own account
broker deposit
ATM withdrawal
loan repayment
cash exchange
```

These should not distort budgeting.

---

## Rule 2 — Budgeting and portfolio tracking are separate domains

Budgeting answers:

```text
Where does my money go?
```

Portfolio tracking answers:

```text
How are my assets performing?
```

They meet at:

```text
net worth
```

---

## Rule 3 — Holding is not the source of truth

The source of truth is:

```text
InvestmentTransaction
```

The calculated state is:

```text
Holding
```

---

## Rule 4 — Imports must be auditable

Every import should answer:

```text
when it happened
where it came from
which file or sync created it
how many rows were imported
how many rows failed
which transactions were created
```

---

## Rule 5 — The app should ask when uncertain

If the app is uncertain, it should not silently guess.

It should create:

```text
TransactionReview
```

and ask the user.

---

## Rule 6 — Category and classification are different

Example:

```text
Category: Investments
Classification: investment_transfer
```

This enables more accurate analytics.

---

## Rule 7 — Historical values require historical exchange rates

For accurate charts and reporting, historical transactions should use historical exchange rates where possible.

---

## Rule 8 — Net worth is an aggregate view

Net worth should combine:

```text
cash
bank accounts
broker cash
investment holdings
crypto holdings
liabilities
```

It should not be manually entered as the primary source of truth.

---

# 27. Recommended MVP Domain Scope

The first MVP should include:

```text
User
Account
Transaction
TransactionSplit
TransactionClassification
TransactionReview
Counterparty
Category
CategoryRule
Budget
BudgetItem
Asset
InvestmentTransaction
Holding
PriceSnapshot
ExchangeRate
ImportBatch
ImportRow
NetWorthSnapshot
```

Postpone:

```text
FinancialGoal
ForecastScenario
SharedAccount
Advanced loan management
Tax reports
Advanced forecasting
Full API bank sync
Full broker API sync
```

---

# 28. MVP Domain Core

The smallest useful product core is:

```text
Account
Transaction
Category
ImportBatch
Budget
Asset
InvestmentTransaction
Holding
ExchangeRate
NetWorthSnapshot
```

This enables:

```text
budgeting
CSV imports
portfolio tracking
net worth calculation
basic dashboard
```

This is the recommended foundation for the first strong MVP.

