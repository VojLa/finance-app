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

Moving across the chart temporarily previews the selected historical snapshot in
the surrounding portfolio cards, currency breakdowns, holdings and allocation.
Leaving the chart restores the current portfolio. Click once to pin the displayed
snapshot so further pointer movement cannot replace it; click the chart again to
release the pin and resume temporary previews.

The comparison line is shown automatically wherever the published snapshot
contains exact evidence and can be hidden with its button. In `Čistá hodnota`
mode it shows `Vložené prostředky`; in `Investice` mode it shows `Investováno`
(the investment cost basis), so account deposits are never compared directly
with investment value. Missing evidence is left as a gap rather than being
interpolated.

For a selected historical point, position quantities use adaptive precision so
small holdings remain visible. Allocation and unrealized return percentages are
shown to one decimal place. A position row is green for a displayed gain, red for
a displayed loss and neutral for zero; a missing or zero cost basis leaves the
return unavailable.

The current and historical portfolio use the same cards, holdings columns,
allocation chart and gain/loss row colours. The holdings table keeps a fixed
five-row viewport, starts with the largest allocation and can be sorted in both
directions from every column heading. `Zobrazit vše` opens the complete sorted
list in a dialog instead of expanding the page.

The allocation pie keeps at most five major holdings as separate slices. A
holding below five percent, and any additional holding beyond those five, is
grouped into `Ostatní`; its tooltip lists every grouped holding. The aggregate
current pie uses portfolio-wide percentages supplied by Python, not account-local
percentages combined in the browser.

Currency cards always reserve exactly three rows, even when zero, one or two
currencies are present. They show at most three currencies inline; any remaining
currencies open in a separate dialog so moving across the chart does not resize
the page.

While history is rebuilding, the last safely published chart can remain visible. If
account access or account scope changed, old points are hidden until rebuilding is
complete. A failed rebuild is shown as failed, and an account with no historical
events shows an empty chart.
