<!-- release: v2.12.1403 -->

## What's Changed

**Recovery guidance for Tesla integrations after an affected update**
PowerSync now detects incompatible Tesla libraries left behind by an earlier update and shows recovery steps in Home Assistant’s Repairs page. If Tesla Fleet, Teslemetry or Tessie stopped loading, update PowerSync to this release, create a backup, then run `ha core rebuild` in Terminal & SSH on Home Assistant OS; a normal restart can leave the old libraries installed. Container recovery steps are included in the repair notice and [troubleshooting guide](https://github.com/bolagnaise/PowerSync/wiki/Troubleshooting#tesla-integrations-fail-after-a-powersync-update).

Update available via HACS
