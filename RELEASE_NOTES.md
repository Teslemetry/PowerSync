<!-- release: v2.12.1376 -->

## What's Changed

**Amber Spike Protection now blocks automatic grid charging**

Fixed an inverted Spike Protection calculation that could lower expensive Amber import forecasts to 50 c/kWh while leaving those periods eligible for battery charging. Smart Optimization now keeps the selected real prices for charts, maximum grid-charge price checks and Cost Neutral accounting, and blocks automatic grid battery charging during Amber's `spike` and `potential` intervals. The execution guard checks live interval flags before applying cached charge actions and stops an existing optimizer-owned charge when a spike starts. Failed restores retain ownership for retry. Solar charging remains available, and user-started Force Charge and Monitoring Mode retain their existing authority.

Spike Protection takes precedence over an automatic Charge By Time target when protected intervals remove its remaining charging opportunities. It does not guarantee zero household imports, force exports, or guarantee that a forecast spike will occur.

**Sigenergy spike tariff overrides no longer lower expensive buy rates**

Fixed the matching 50 c/kWh downward override in Sigenergy tariff sync. Protected buy rates above its existing 100 c/kWh threshold are now raised toward a value above the highest scheduled sell price; already higher prices are preserved. This removes the artificial cheap-import signal from the native tariff schedule while Smart Optimization uses its separate charging restriction.

**Amber and optimiser wiki guidance updated**

Added [Amber Spike Protection and Forecast Confidence Alert guidance](https://github.com/bolagnaise/PowerSync/wiki/Electricity-Providers#amber-spike-protection), including what the alert means and how forecast selection differs from a charging restriction. Updated [Disable Idle](https://github.com/bolagnaise/PowerSync/wiki/Smart-Optimization#disable-idle) for every provider, its precedence over deadline holds, the Profit Max confidence-decay horizon, and small planned exports whose estimated earnings round to $0.00.

Verified with 391 focused and adjacent tests covering price construction, the real solver, grid-charge constraints, runtime ownership and restore failures, Sigenergy tariff/control behaviour, and Cost Neutral accounting. This release is not a live hardware verification of the reporter's system.

Update available via HACS
