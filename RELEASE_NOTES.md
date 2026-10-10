<!-- release: v2.12.1373 -->

## What's Changed

**Keep multi-resource Solcast forecasts complete**

Built-in Solcast polling now treats a multi-resource update as transactional. If a configured resource is skipped, fails, or returns a forecast with incomplete period coverage, PowerSync keeps a verified complete fallback or reports the forecast unavailable instead of publishing one site's values as the whole system. Forecast cache entries now carry resource identity so legacy partial multi-site values cannot be silently restored.

Regression coverage includes empty and misaligned secondary responses, complete two-site aggregation, complete-cache fallback, and rejection of legacy multi-resource cache data without completeness metadata.

Update available via HACS
