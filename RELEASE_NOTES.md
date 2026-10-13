<!-- release: v2.12.1393 -->

## What's Changed

**Charge By Time avoids unnecessary overnight holds**
When PowerSync needs a fallback charging plan, it now includes unused forecast solar when deciding whether the battery can supply the home before the charging deadline. This avoids unnecessary overnight holds while keeping the later solar charging, planned battery level, and grid flows consistent with the selected target and charging limits.

Warnings about an earlier unsuccessful calculation can still appear when a fallback plan is produced.

Update available via HACS
