<!-- release: v2.12.1440 -->
## Native Tesla Charge on Solar

You can now read and manage Tesla's native Charge on Solar from Home Assistant using a Teslemetry vehicle connection. The new actions let you enable or disable native solar charging and set its lower and upper charge limits.

Complete Tesla's Charge on Solar setup first, then turn off PowerSync EV charging sessions and other charging controllers. Enabling requires confirmation that your Tesla and Powerwall meet Tesla's requirements, including a site without export or site limits. Native mode follows Tesla's charging behavior; PowerSync price, phase-management and grid-import rules do not apply.

## Confirmed handover

PowerSync holds its EV control while native solar is enabled or a request cannot be confirmed. To return to PowerSync charging, disable native mode, confirm disabled settings with the read action, and then start your chosen PowerSync mode. The hold survives Home Assistant restarts.

The actions use Teslemetry credits and may wake a sleeping vehicle. Reads are explicit, with no background native polling. See the [Services Reference](https://github.com/bolagnaise/PowerSync/wiki/Services-Reference#native-tesla-charge-on-solar-teslemetry) for setup, costs and recovery.
