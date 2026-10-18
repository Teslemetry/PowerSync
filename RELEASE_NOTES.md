<!-- release: v2.12.1427 -->

## What's Changed

**Enphase Envoy Installer curtailment**
PowerSync can now use the Enphase Envoy Installer integration's DPEL controls for native zero-export load following or a production limit that follows site demand. Choose **Enphase (Envoy Installer integration)** under **Configure > AC Inverter**, then enter your Envoy entity prefix; working DPEL controls and the required Enphase permissions must already be configured in that integration.

PowerSync saves the previous DPEL mode, watt limit, and enabled state for restoration, including after a restart, and refuses to overwrite changes made by another controller. Manual shutdown requests a production limit of 0 W; native zero-export mode keeps solar available for local demand.

Update available via HACS
