# Fronius GEN24 Storage

PowerSync supports Fronius GEN24 storage systems, including BYD Battery-Box and Fronius Reserva batteries, through the Fronius Modbus companion integration.

## Prerequisites

- Install `callifo/fronius_modbus` from HACS.
- Configure your GEN24 inverter in that integration before adding it to PowerSync.
- Provide the Fronius local customer password in the Fronius Modbus integration when available. This lets the companion integration expose the Web API battery controls used for reliable charge-from-grid behavior.

## PowerSync Setup

1. Add the PowerSync integration.
2. Select `Fronius GEN24 storage (BYD/Reserva)` as the battery system.
3. Select the Fronius Modbus integration entry if more than one is configured.
4. Enter usable battery capacity and maximum charge/discharge power for optimizer fallback values.

PowerSync reads Home Assistant entities exposed by `fronius_modbus` for battery control. Solar curtailment can also use that integration’s native export-limit control as described below; its fallback AC output control uses a direct Modbus connection.

## Supported Controls

- Force charge from grid
- Force discharge/export to grid
- Hold SOC
- Restore normal automatic storage control
- Set backup reserve / minimum SOC
- Smart Optimization dispatch

## Site export limit

Profit Max solar export needs a known finite site export cap before it will hold battery charging to push solar to the grid.

PowerSync auto-detects it from the `fronius_modbus` **Export soft limit** sensor. That sensor only exists when the Fronius Web API is configured in the companion integration, and it only reports a value while Export Limit Control's soft limit is enabled on the inverter.

If you do not have it, set **Maximum grid export** under Configure → Smart Optimization → Grid & site constraints to your site/DNSP export cap in kW. Leaving it blank keeps solar export permanently off; `sensor.power_sync_optimization_status` reports `profit_max_solar_export.capability.reason` as `export_limit_not_configured` and a repair is raised.

If setup reports missing Fronius storage entities, confirm that the Fronius Modbus integration has created storage `sensor`, `select`, and `number` entities and that the battery system is online.

## Solar curtailment

For a GEN24 with a Fronius Smart Meter, PowerSync prefers the companion integration’s **Export soft limit** number when it belongs to the configured solar inverter. This uses the inverter’s own meter-based load following: PowerSync sets the site export limit to 0 W, allowing solar to supply the home while limiting export. A working AC output-limit setting alone does not establish that the inverter is reducing export.

The companion integration must already expose an available **Export soft limit** number in watts. This requires its local technician Web API access. PowerSync matches the solar inverter host to one companion integration entry and uses only that entry’s registered control; it does not choose an entity by a generic name or obtain credentials itself.

PowerSync saves the existing soft limit before changing it and restores that exact value when curtailment ends. The saved value survives a PowerSync reload or Home Assistant restart. If a write or restore fails, PowerSync retains the saved value for retry. Leave other export-limit automations disabled while PowerSync owns this control.

When no native export-limit number is exposed for the configured inverter, the existing Modbus AC-limit mode remains available. If a native control becomes unavailable during a PowerSync session, PowerSync retains its restore obligation rather than switching controls. Acknowledged settings remain separate from physical confirmation: the curtailment status stays pending until fresh site readings show export at or below 100 W.
