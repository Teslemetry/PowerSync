<!-- release: v2.12.1383 -->

## What's Changed

**Optional Amber Forecast Confidence for Smart Optimization**
Amber users can enable a separate Amber Forecast Confidence switch in Battery & Forecast Inputs or on the Smart Optimization device. It is off by default. The optimizer reduces the premium assigned to high future export forecasts, allowing an available export opportunity to compete more strongly with a larger, more distant forecast spike.

**Preserve real prices and existing control boundaries**
Only future forecast valuation changes. Current prices, displayed tariffs, settlement accounting and export eligibility retain their original rates, including signed negative prices. Export Boost and Chip Mode still evaluate their eligibility against real rates. Cost Neutral retains raw settlement accounting, and Spread Export respects the resulting price boundaries. When source metadata or ordinary-price samples are insufficient, the optimizer falls back to its existing export-confidence policy.

**Settings, diagnostics and mobile support**
The preference persists through restarts and is available through optimizer settings, with accepted-plan diagnostics on the Optimizer Current Action sensor. Compatible PowerSync Mobile builds can display the Amber-only control after this integration advertises support. The updated wiki explains activation, fallback and the provisional 90-minute half-life heuristic. This feature is a scheduling preference, not a measured confidence probability or a guarantee of better returns.

Update available via HACS
