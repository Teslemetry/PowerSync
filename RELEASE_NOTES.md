<!-- release: v2.12.1416 -->

## What's Changed

**Disable Idle now accounts for Charge By Time consumption**

When Disable Idle replaces an optimizer idle hold with `self_consumption`, the projected battery path and deadline feasibility check now use that effective action. If the target cannot be reached after serving the home load, PowerSync reports the deadline as infeasible instead of advertising an idle-dependent plan.

Update available via HACS
