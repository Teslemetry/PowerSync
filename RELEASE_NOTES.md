<!-- release: v2.12.1392 -->

## What's Changed

**Accurate grid export in charging plans**
When the battery supplies the home while exporting, the charging plan now shows the full expected grid export without counting household use twice. This corrects understated export values, including exports previously shown as zero; planned EV charging is also included in the calculation.

The corrected values are forecasts. Current inverter power readings are still needed to confirm actual export.

Update available via HACS
