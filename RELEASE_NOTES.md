<!-- release: v2.12.1458 -->
## Tesla charge forecasts while asleep or unplugged

PowerSync now uses fresh Tesla schedules already held by Home Assistant after a restart, even while the car sleeps. Schedule and battery data keep their freshness limits, so old or missing readings do not become a new charge plan.

Future charging now uses a valid nominal supply voltage when Tesla reports a near-zero unplugged voltage. This fixes nearly invisible EV forecasts such as a 32 W plan caused by a 2 V reading.

## See planned Tesla charge windows

Mobile build 448 adds a Home charge forecast on the optimisation screen and under EVs & Chargers, showing each car's forecast times, energy and power even when Smart EV Charging is off. Overlapping windows still count once. Update both Home Assistant and the mobile app to see the new window list.
