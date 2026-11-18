# Prompt used to build the dashboard

> Build an automatically refreshing dashboard that monitors Japan's economy and helps answer one question:
> **Is Japan's inflation persistent enough for the Bank of Japan to keep raising rates, and what does that mean for the yen?**
>
> Requirements:
> 1. Use 7 indicators from primary or official sources: USD/JPY (Federal Reserve H.10), the overnight call rate as the BOJ policy-rate proxy, the 10-year JGB yield (Ministry of Finance CSV files), headline and core (less fresh food) CPI read directly from the Statistics Bureau of Japan's CSV files, real GDP (Cabinet Office), the unemployment rate (Statistics Bureau), and the BIS real effective exchange rate of the yen. Retrieve them from FRED's public CSV endpoint where the series is mirrored there, and directly from the MOF website for the JGB yield, with a FRED fallback.
> 2. Show each indicator as a chart from 2010 to the latest observation. Under each chart, state the units, data frequency, original source, retrieval route, any transformation, and the latest observation date and value.
> 3. Transformations: CPI and real GDP as year-over-year % changes (12 months and 4 quarters). Add the BOJ 2% target line to the CPI chart, and the long-run average to the REER chart so over- or undervaluation is visible.
> 4. State the exchange-rate conventions: USD/JPY in yen per dollar (a rise = a weaker yen); REER rises when the yen strengthens.
> 5. Show the date and time of the last successful refresh at the top of the page, separately from each chart's latest observation date. If a source fails, keep the last saved data, mark that series as failed, and do not overwrite the last successful refresh time when nothing was updated.
> 6. Flag a series as stale when its latest observation is older than expected for its frequency.
> 7. Append one row per series per run to a refresh log (run time, status, latest observation date, latest value).
> 8. Automate with a GitHub Actions workflow that runs daily after the MOF release (01:17 UTC) and on demand, commits the data, and publishes the page through GitHub Pages from the docs/ folder.
> 9. Use Python (pandas, plotly, requests), one script, simple layout.

## Follow-up instructions during development
- "FRED requests fail from the script. Find out why and fix it." (Cause: FRED rejects some custom User-Agents.)
- "The FRED CPI series for Japan ends in 2021. Replace it with the Statistics Bureau's own CSV files; splice year-over-year rates across base years and keep older history from OECD, and explain the splice on the chart."
- "Reference lines are missing and the first chart is clipped. Fix the layout and check it with a screenshot."
