<!-- release: v2.12.1432 -->

## What's Changed

**Amber daily supply charge**
Amber Metered Today and other Amber metered totals now use the Daily supply charge saved under Smart Optimization, including when Cost Neutral is off. A saved rate of $1.08/day now contributes $1.08 per day instead of the default monthly allowance.

**Live settings updates and existing plans**
Saving a daily rate updates subsequent summaries without restarting Home Assistant or waiting for another Amber usage fetch. An explicit zero means no daily supply charge; installations without a valid daily rate keep the monthly allowance fallback. The current saved rate applies to all days shown, including historical summaries.

Update available via HACS
