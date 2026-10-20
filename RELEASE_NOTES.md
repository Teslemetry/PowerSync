<!-- release: v2.12.1435 -->
## Cost Neutral counts solar credits from the final plan

Cost Neutral now credits solar export from its selected plan before deciding how much battery export is still needed to cover the day’s costs. This reduces unnecessary small battery-export windows when an export action releases extra solar to the grid. Surplus solar remains uncapped, and small battery exports can still appear while costs remain uncovered.

Manual charge and discharge requests also keep their ownership through plan accounting, so Cost Neutral does not trim a user’s active request.

Update through HACS and restart Home Assistant to load the fix.
