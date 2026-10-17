<!-- release: v2.12.1418 -->

## What's Changed

**Stop solar during negative import prices**
A new optional setting stops solar production when your current retail import price is below zero, allowing household loads and permitted battery charging to use paid grid imports. Enable **Stop solar when the import price is negative** in **Curtailment settings**; it is off by default and keeps your existing battery, charging and electrical limits.

**Native inverter controls and support for other brands**
Native production controls cover Enphase, separate Fronius solar inverters, standalone Sungrow SG, SolarEdge, Zeversolar and compatible Sigenergy DC solar configurations. Other brands, including hybrid systems, need an independently verified PV-only production switch or limit exposed in Home Assistant; export limits and whole-hybrid shutdown controls are unsuitable. See the [configuration and inverter coverage guide](https://github.com/bolagnaise/PowerSync/wiki/Negative-Import-Solar) before enabling it.

**Recovery and clearer confirmation**
PowerSync saves the previous production settings and restores the settings it still owns when the price reaches zero, the current price expires, or the option is disabled. Fresh grid-connection evidence is required, and the new **Solar Production Control** sensor keeps stops pending until fresh solar readings confirm the reduction. Persistent stops need Home Assistant and inverter connectivity to recover.

**Solar forecasts follow confirmed coverage**
Sites with confirmed controls covering every solar source can enable **These controls cover all solar generation** so charging plans account for stopped solar during negative-price periods. Mixed sites keep their solar forecast, and deliberate production stops are excluded from forecast learning.

Update available via HACS
