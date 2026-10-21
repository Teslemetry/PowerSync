<!-- release: v2.12.1456 -->

## Native Tesla solar through PowerSync Fleet

Tesla Charge on Solar can now use your PowerSync Fleet connection as well as Teslemetry. Register your vehicle in PowerSync Cloud, grant vehicle permissions and pair its PowerSync virtual key. Complete native Charge on Solar setup in the Tesla app at a compatible Powerwall site first.

The mobile vehicle card identifies the provider and offers explicit settings reads and confirmed changes to both charge limits. Provider request costs apply. Fleet uses an extended vehicle protocol; this release has source and build validation, with live vehicle acceptance still unverified.

## Controller handoff

Both HA and Cloud hold PowerSync EV control until a complete readback confirms native solar is disabled. Monitoring mode, active charging sessions, request cooldowns and the daily Fleet command budget remain enforced. Existing Tesla schedule planning and No solar installed protections remain included.
