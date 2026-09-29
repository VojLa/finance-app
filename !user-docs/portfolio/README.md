# Portfolio and dashboard

Portfolio shows only investment accounts: broker, exchange and crypto wallet. The dashboard remains the complete financial overview of all accessible accounts. Account views use the account display currency; aggregate views use the base currency. The chart and cards come from one complete published snapshot set, so values cannot mix an old and a partially rebuilt state.

When an account contains multiple currencies, the main number is converted to
the selected display currency using the saved snapshot valuation evidence. The
currency breakdowns retain the original amounts (for example, EUR and USD)
and are evidence, not amounts to add together. Deposits and invested cash use
the exchange rate applicable on the event date, which can differ from today's
rate.

## Portfolio history

The portfolio chart offers `1D`, `1W`, `1M`, `3M`, `6M`, `1Y`, `5Y`, `10Y` and
`ALL`. Older and newer parts of one chart can have different truthful resolutions;
the point tooltip shows the resolution actually used. The application does not
invent intraday values from daily data.

The chart follows the account selected above it. Choose `Vše` for the aggregate;
the chart then uses the same complete published history generation rather than a
browser-calculated sum.

The `Vložené prostředky` overlay stays visible but disabled until the published
snapshot series contains its exact deposited and investment-cost evidence.

While history is rebuilding, the last safely published chart can remain visible. If
account access or account scope changed, old points are hidden until rebuilding is
complete. A failed rebuild is shown as failed, and an account with no historical
events shows an empty chart.
