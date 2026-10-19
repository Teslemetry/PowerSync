<!-- release: v2.12.1429 -->

## What's Changed

**Clear phantom EV power after Tesla charging finishes**
Tesla BLE charging could remain active or appear as an extra "Wall Connector" after unplugging, leaving Home Load too low until PowerSync was reloaded. PowerSync now keeps its calculated EV total separate from actual charger readings, so old charging power cannot feed back into the display and Home Load calculation. Real Wall Connector and Home Assistant charger meters remain supported.

Update through HACS and restart Home Assistant.

Update available via HACS
