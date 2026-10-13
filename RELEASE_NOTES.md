<!-- release: v2.12.1390 -->

## What's Changed

**Keep native solar charging after Cost Neutral export projection is clipped**
When Cost Neutral temporarily projects an export witness at the optimizer reserve, the emitted `self_consumption` action now retains available native solar charging instead of publishing zero battery charge and fictitious solar export. The final SOC, grid flow, and settlement values are recomputed from the executable action.

## Regression coverage

Added a five-minute Sigenergy-style regression covering the reported unequal optimizer/hardware reserve case: 3 kW solar, 2 kW load, 5% optimizer reserve, and 2% hardware reserve. Existing Cost Neutral, budget, hardware-floor, and battery-export guard suites also pass.

Update available via HACS
