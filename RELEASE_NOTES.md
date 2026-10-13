<!-- release: v2.12.1394 -->

## What's Changed

**Powerwall local setup no longer conflicts with Home Assistant's protobuf pin**
PowerSync now selects a compatible Tesla protocol version when Home Assistant supplies protobuf 6.32.0, so the integration can start without manually changing Home Assistant's protobuf package. Tesla Powerwall local diagnostics continue to support both older and newer response formats.

Update available via HACS
