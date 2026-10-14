<!-- release: v2.12.1398 -->

## What's Changed

**Safer Zaptec price-level stop confirmation**
Zaptec price-level charging now keeps PowerSync's charging ownership and home-battery preservation active until a fresh charger poll, started after the stop request, confirms that charging has ceased. This prevents an older waiting response from being mistaken for confirmation.

**Keep finished Zaptec chargers visible**
A connected Zaptec charger that has finished its session remains visible in the EV loadpoint card instead of appearing as if no EV loadpoints are configured.

Update available via HACS
