<!-- release: v2.12.1387 -->

## What's Changed

**Accurate GoodWe solar and household load with AC-coupled generation**
GoodWe installations can now select an optional **Whole-site solar power sensor
(all PV)** that includes both the hybrid inverter's PV strings and separate
arrays such as Enphase microinverters. PowerSync uses this total for solar
nowcasting and forecast learning, avoiding under-reported generation that can
make the optimizer plan unnecessary grid charging.

Household load is rebuilt from the site solar, grid and battery power balance.
This preserves the correct load even when GoodWe reports negative house
consumption: for example, 4 kW of total solar with 2 kW of export and no battery
movement reports 2 kW of household load. Corrected figures also feed daily energy
accumulation. A missing, unavailable or unusable selected sensor marks the solar
sample invalid and skips its learning and energy accumulation while retaining
the inverter-only readings for display.

Choose the sensor once on **Battery connection method & sensors** during setup,
including the Home Assistant GoodWe connection path. Existing users can select,
replace or clear it through the connection-profile or direct GoodWe options
forms. The selection persists across reload, and clearing it restores the normal
inverter-only telemetry. Leave the optional field empty when all solar is wired
to the GoodWe. Setup guidance is documented in the GoodWe guide and wiki.

**Restore Powerwall local system-info diagnostics with tesla-protocol 4.0.0**
Powerwall local diagnostics now read the updated DIN and firmware fields from
tesla-protocol 4.0.0. This fixes an AttributeError on installations using the new
protocol response shape and restores gateway identity, firmware version and
firmware hash reporting. The integration's minimum tesla-protocol requirement is
now 4.0.0 so Home Assistant installs a compatible dependency during the update.

## Regression coverage

GoodWe coverage includes both real telemetry adapters, signed-load correction,
unavailable sensor handling, setup and edit persistence, sensor replacement and
clearing with real voluptuous validation, and the Home Assistant setup route.
Powerwall coverage validates the actual 4.0.0 protobuf response, empty and missing
responses, read-only diagnostics, and adjacent pairing, signaling, telemetry and
battery health behavior. HACS and Hassfest validation passed for both PRs.

Thanks to @ArChAnG3LsFuRy for #131 and @Bre77 for #133.

Update available via HACS
