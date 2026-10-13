<!-- release: v2.12.1395 -->

## What's Changed

**PowerSync setup respects Home Assistant's existing protobuf version**
PowerSync now bundles its Powerwall local message definitions, removing a Tesla package dependency that could block setup on the advertised minimum Home Assistant Core version. This also avoids forcing that dependency onto Sigenergy and other battery setups. Update through HACS and restart Home Assistant; this fix does not require raising PowerSync's minimum Core version.

**Accurate planning timeout diagnostics**
When a later planning check runs out of time or reaches a calculation limit, PowerSync now reports the actual reason while keeping the usable plan. It still checks that retained plan against your charging deadline and preserves the existing reserve safeguards.

Update available via HACS
