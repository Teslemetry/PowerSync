<!-- release: v2.12.1415 -->

## What's Changed

**Solar Surplus keeps retrying unsuccessful battery-floor stops**

An EV could keep charging after the home battery fell below its Solar Surplus pause threshold if the stop failed or could not be confirmed. PowerSync now shows the unsuccessful or unconfirmed stop and retries at a controlled interval, including with Parallel Charging, instead of recording zero charging current and abandoning the stop.

Update through HACS and restart Home Assistant. Weak Tesla BLE coverage may still prevent a stop from reaching the car; check fresh vehicle readings to confirm charging has stopped.

Update available via HACS
