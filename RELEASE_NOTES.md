<!-- release: v2.12.1386 -->

## What's Changed

**Keep optimizer mode projections aligned with executable battery flows**
The optimizer no longer reports sub-threshold grid charging, or the resulting
SOC increase, after the projected action has become `idle` or
`self_consumption`. Non-charge actions can retain only native solar charging;
export actions retain their battery discharge and reserve limits.

When a command-mode projection cannot satisfy a Charge By Time deadline using
the emitted flows, the retained plan is now marked infeasible with an explicit
diagnostic instead of advertising a physically unreachable SOC target. The
safe existing fallback remains in place and no hardware command is inferred
from the retained plan.

## Regression coverage

Regression tests cover the reported constrained-import twelve-slot case with
Cost Neutral enabled and disabled, the below/equal/above 100 W action threshold,
native-solar-only self-consumption charging, and the adjacent Cost Neutral,
budget, battery-export, and Profit Max guard suites.

Update available via HACS
