<!-- release: v2.12.1425 -->

## What's Changed

**SolarEdge household supply after negative import pricing**
When import pricing becomes zero or positive, SolarEdge export curtailment now permits solar and battery supply up to household demand and battery charging instead of retaining a full stop. The output limit follows demand every 30 seconds; brief import or export remains possible as demand changes and the inverter rounds its limit.

Update available via HACS
