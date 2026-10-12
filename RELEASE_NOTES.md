<!-- release: v2.12.1380 -->

## What's Changed

**AEMO Spike Detection now respects the saved off switch**
Fixed a lifecycle gap where an existing spike handler could keep running after Spike Detection was saved as off in the mobile app. Tesla, other supported battery spike handlers, and the GloBird/AEMO VPP optimizer path now re-check the live setting before starting or re-arming spike export. Saving the enable switch, NEM region, or threshold reloads PowerSync automatically; an in-flight price or Tesla baseline request cannot start a new spike export after disable.

**Restore active Tesla spike events when disabling or restarting**
PowerSync retires and waits for spike handlers during reload, restores the saved pre-spike tariff and operation mode, and recovers pending Tesla events even when Spike Detection is off. The restore obligation is saved before the first Tesla mutation. Failed restores remain pending, and PowerSync avoids returning Tesla to autonomous mode while a spike tariff still needs restoration. Missing tariff baselines or unreadable recovery records block new spike export instead of guessing a baseline. Monitoring Mode continues to block hardware commands, and service-based spike cleanup preserves later manual commands.

This fixes a reproduced code path; it does not establish the cause of every historical export event. AEMO Spike Detection remains separate from Amber Spike Protection, price alerts, normal Tesla tariff behaviour, and Smart Optimization. In the mobile app, tap **Save Changes** after editing the switch.

Update available via HACS
