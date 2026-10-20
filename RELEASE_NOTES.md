<!-- release: v2.12.1441 -->

## Tesla Powerwall connection recovery

Switching back to Tesla after using Amber Smart Shift or another battery controller now asks you to select your Tesla energy site before reloading. If setup already reports a missing energy site, update and restart Home Assistant, then open **Configure → Tesla API connection** and choose your site again.

Amber Smart Shift continues to provide timed battery modes; Powerwall solar curtailment and Tesla's Grid Export setting require the Tesla control path.
