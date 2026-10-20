<!-- release: v2.12.1443 -->

## Fixed

### Powerwall discharge cleanup

Fixed a missed battery charge check when restoring Powerwall settings after force discharge, including a failed start. A saved backup reserve above the measured battery charge is now left unapplied to avoid triggering grid charging; set your intended reserve manually if notified.
