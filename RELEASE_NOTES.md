<!-- release: v2.12.1428 -->

## What's Changed

**Clear stale Tesla BLE power after charging finishes**
Tesla BLE charging could keep showing the previous power reading after the car reached its charge limit, making Home Load incorrect until the cable was unplugged. PowerSync now ignores attribute-only refreshes of those readings when reconciling a stopped or completed charge.

Update available via HACS
