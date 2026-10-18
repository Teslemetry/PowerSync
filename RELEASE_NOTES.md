<!-- release: v2.12.1423 -->

## SolarEdge curtailment recovery

SolarEdge curtailment now checks the current power limit and reapplies it if an inverter reset has removed it. When the limit cannot be verified, curtailment stays Pending until a later check can confirm it, instead of continuing to show the old active state.
