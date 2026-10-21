<!-- release: v2.12.1451 -->
## Existing Tesla charging schedules

The battery optimiser now includes home charging schedules stored in your Tesla, even when PowerSync Smart EV charging is off or unconfigured. When both have schedules, overlapping windows count once per car so the same free-electricity period is not counted twice. Separate vehicles still count separately.

Requires a loaded Home Assistant Tesla Fleet or Teslemetry vehicle integration. Schedule discovery reads online vehicles at most once every 15 minutes and can incur provider charges; known sleeping cars are skipped and no wake command is issued. Tesla Powerwall/Wall Connector Smart Charging plans are outside this vehicle-schedule API.

## Tesla Charge on Solar in the mobile app

PowerSync Mobile build 445 adds explicit native Charge on Solar controls under EVs & Chargers. With a Teslemetry vehicle connection, read Tesla settings, choose the charge-from-any-source and excess-solar limits, then confirm before applying. Native settings requests may wake the car and spend Teslemetry credits.

PowerSync keeps its EV control hold until disabled native settings are confirmed. The No solar installed setting blocks new activation while preserving reading, disabling and existing ownership protection. Monitoring mode and active-session restrictions still apply.
