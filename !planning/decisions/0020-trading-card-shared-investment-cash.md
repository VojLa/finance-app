# ADR 0020 - Trading Card ve sdilene hotovosti investic

Status: Accepted
Date: 2026-09-01
Decision owners: vlastnik finance-app

## Rozhodnuti

Trading 212 `Card debit` a `New card cost` jsou bezne canonical transakce na
stejnem broker uctu jako investicni udalosti. Snizuji skutecnou hotovost a
`netDeposits` jako externi vyber, ale nejsou investicni P/L, fee ani tax.
`Spending cashback` je bezny externi vklad, nikoli investicni urok.

Broker, exchange a crypto-wallet replay proto smi zpracovat tyto presne
klasifikovane cashflow transakce vedle investicnich udalosti. Portfolio a jeho
historie zobrazuji pozice i skutecnou zbyvajici hotovost; net-worth zpracovava
stejny canonical stav bez druheho uctu.

## Dusledky

- import Trading 212 nesmi karetní radky zahodit ani je mapovat na investicni urok;
- aktualni i historicky replay musi pocitat stejny cash a net-deposit dopad;
- jine bezne transakce na investicnim uctu zustanou fail-closed, dokud nemaji
  explicitni canonical klasifikaci.
