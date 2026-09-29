import type { PortfolioSnapshotData } from "@/modules/python-api/snapshot-workflow-contract"

export function portfolioSnapshotFixture(): PortfolioSnapshotData {
  return {
    asOf: "2032-08-02T12:30:00.000",
    baselineTimestamp: "2032-08-02T00:00:00.000",
    historyAnchorSnapshotId: "net-worth-baseline",
    valuationTimestamp: "2032-08-02T12:29:00.000",
    isStale: false,
    currency: "EUR",
    calculationVersion: 7,
    summary: {
      cashValue: "12.340000",
      cashByCurrency: [
        { currency: "CZK", amount: "10000.000000" },
        { currency: "EUR", amount: "12.340000" },
        { currency: "USD", amount: "-50.000000" },
      ],
      investmentValue: "999999999999.999999",
      investmentCostBasis: "700.000001",
      liabilitiesValue: "-123.450000",
      totalValue: "777.123456",
      netDepositsValue: "500.000000",
      netDepositsByCurrency: [
        { currency: "CZK", amount: "25000.000000" },
        { currency: "EUR", amount: "500.000000" },
      ],
      realizedPnlValue: "-2.500000",
      unrealizedPnlValue: "77.123455",
      feesValue: "1.000000",
      taxesValue: "0.500000",
      accountCount: 2,
      positionCount: 2,
    },
    accounts: [
      {
        baselineSnapshotId: "snapshot-a-czk",
        primaryBaselineSnapshotId: "snapshot-a",
        currency: "CZK",
        account: {
          accountId: "account-a",
          accountType: "broker",
          currency: "CZK",
          name: "Broker A",
        },
        summary: {
          cashValue: "10.000000",
          cashByCurrency: [
            { currency: "CZK", amount: "10000.000000" },
            { currency: "EUR", amount: "10.000000" },
          ],
          investmentValue: "123.456789",
          investmentCostBasis: "100.000001",
          liabilitiesValue: "-23.450000",
          totalValue: "110.006789",
          netDepositsValue: "480.000000",
          netDepositsByCurrency: [
            { currency: "CZK", amount: "25000.000000" },
            { currency: "EUR", amount: "480.000000" },
          ],
          realizedPnlValue: "-2.500000",
          unrealizedPnlValue: "23.456788",
          feesValue: "1.000000",
          taxesValue: "0.500000",
          positionCount: 1,
        },
        positions: [
          {
            allocationPct: "60.0000",
            assetId: "asset-a",
            assetType: "stock",
            costBasis: "100.0000010000",
            costCurrency: "CZK",
            listingId: "listing-a",
            name: "Asset A",
            nativeCostBasis: "2500.0000000000",
            nativeCostBasisByCurrency: [{ currency: "CZK", amount: "2500.0000000000" }],
            nativeCostCurrency: "CZK",
            nativeValue: "3000.1234560000",
            nativeValueCurrency: "CZK",
            priceCurrency: "CZK",
            pricePerUnit: "3000.1234560000",
            priceTimestamp: "2032-08-01T12:30:00.123",
            quantity: "1.0000000000",
            symbol: "AAA",
            unrealizedPnl: "23.4567880000",
            value: "123.456789",
            valueCurrency: "CZK",
          },
        ],
      },
      {
        baselineSnapshotId: "snapshot-b-usd",
        primaryBaselineSnapshotId: "snapshot-b",
        currency: "USD",
        account: {
          accountId: "account-b",
          accountType: "crypto_wallet",
          currency: "USD",
          name: "Wallet B",
        },
        summary: {
          cashValue: "2.340000",
          cashByCurrency: [
            { currency: "EUR", amount: "2.340000" },
            { currency: "USD", amount: "-50.000000" },
          ],
          investmentValue: "40.000000",
          investmentCostBasis: "30.000000",
          liabilitiesValue: "-100.000000",
          totalValue: "-57.660000",
          netDepositsValue: "20.000000",
          netDepositsByCurrency: [{ currency: "EUR", amount: "20.000000" }],
          realizedPnlValue: "0.000000",
          unrealizedPnlValue: "10.000000",
          feesValue: "0.000000",
          taxesValue: "0.000000",
          positionCount: 1,
        },
        positions: [
          {
            allocationPct: "100.0000",
            assetId: "asset-b",
            assetType: "crypto",
            costBasis: "30.0000000000",
            costCurrency: "USD",
            listingId: "listing-b",
            name: "Asset B",
            nativeCostBasis: "35.0000000000",
            nativeCostBasisByCurrency: [{ currency: "USD", amount: "35.0000000000" }],
            nativeCostCurrency: "USD",
            nativeValue: "45.0000000000",
            nativeValueCurrency: "USD",
            priceCurrency: "USD",
            pricePerUnit: "45.0000000000",
            priceTimestamp: "2032-08-01T12:30:00.123",
            quantity: "1.0000000000",
            symbol: "BBB",
            unrealizedPnl: "10.0000000000",
            value: "40.000000",
            valueCurrency: "USD",
          },
        ],
      },
    ],
    aggregatePositions: [
      {
        accountId: "account-a",
        accountName: "Broker A",
        accountCurrency: "CZK",
        position: {
          allocationPct: "60.0000",
          assetId: "asset-a",
          assetType: "stock",
          costBasis: "100.0000010000",
          costCurrency: "EUR",
          listingId: "listing-a",
          name: "Asset A",
          nativeCostBasis: "2500.0000000000",
          nativeCostBasisByCurrency: [{ currency: "CZK", amount: "2500.0000000000" }],
          nativeCostCurrency: "CZK",
          nativeValue: "3000.1234560000",
          nativeValueCurrency: "CZK",
          priceCurrency: "CZK",
          pricePerUnit: "3000.1234560000",
          priceTimestamp: "2032-08-01T12:30:00.123",
          quantity: "1.0000000000",
          symbol: "AAA",
          unrealizedPnl: "23.4567880000",
          value: "123.456789",
          valueCurrency: "EUR",
        },
      },
      {
        accountId: "account-b",
        accountName: "Wallet B",
        accountCurrency: "USD",
        position: {
          allocationPct: "100.0000",
          assetId: "asset-b",
          assetType: "crypto",
          costBasis: "30.0000000000",
          costCurrency: "EUR",
          listingId: "listing-b",
          name: "Asset B",
          nativeCostBasis: "35.0000000000",
          nativeCostBasisByCurrency: [{ currency: "USD", amount: "35.0000000000" }],
          nativeCostCurrency: "USD",
          nativeValue: "45.0000000000",
          nativeValueCurrency: "USD",
          priceCurrency: "USD",
          pricePerUnit: "45.0000000000",
          priceTimestamp: "2032-08-01T12:30:00.123",
          quantity: "1.0000000000",
          symbol: "BBB",
          unrealizedPnl: "10.0000000000",
          value: "40.000000",
          valueCurrency: "EUR",
        },
      },
    ],
  }
}

export function anycoinIncompletePortfolioSnapshotFixture(): PortfolioSnapshotData {
  const fixture = portfolioSnapshotFixture()
  const anycoinAccount = fixture.accounts[1]
  const anycoinAggregate = fixture.aggregatePositions[1]
  if (anycoinAccount === undefined || anycoinAggregate === undefined) {
    throw new Error("Portfolio fixture is missing the Anycoin account.")
  }

  fixture.summary.investmentCostBasis = null
  fixture.summary.netDepositsValue = null
  fixture.summary.netDepositsByCurrency = null
  fixture.summary.realizedPnlValue = null
  fixture.summary.unrealizedPnlValue = null

  anycoinAccount.account.name = "Anycoin BTC"
  anycoinAccount.summary.investmentCostBasis = null
  anycoinAccount.summary.netDepositsValue = null
  anycoinAccount.summary.netDepositsByCurrency = null
  anycoinAccount.summary.realizedPnlValue = null
  anycoinAccount.summary.unrealizedPnlValue = null

  for (const position of [anycoinAccount.positions[0], anycoinAggregate.position]) {
    if (position === undefined)
      throw new Error("Portfolio fixture is missing the Anycoin position.")
    position.costBasis = null
    position.costCurrency = null
    position.unrealizedPnl = null
    position.nativeCostBasis = null
    position.nativeCostCurrency = null
    position.nativeCostBasisByCurrency = null
  }
  return fixture
}
