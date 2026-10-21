<!-- release: v2.12.1455 -->

## Tesla tariff restoration

Turning off an already inactive Force Charge or Force Discharge switch no longer replaces your Tesla tariff with an old cached tariff. This prevents automations that repeatedly turn those switches off from bringing back a previous provider's rates.

Genuine override and restart recovery still restore the saved settings. For Other / Custom TOU, recovery without a saved tariff now uses your configured custom rates before the historical cache. Update PowerSync and reload the integration before correcting your EDF or other provider's tariff in Tesla; Custom TOU still does not sync automatically.
