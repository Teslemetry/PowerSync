<!-- release: v2.12.1453 -->

## Amber metered costs use the correct billing day

Amber's final usage interval now stays on its billing day instead of appearing on the following day. This prevents yesterday's final zero interval from making Today Metered Cost show a misleading billable zero while today's metered data is still unavailable.

Update through HACS and reload PowerSync. Previous metered totals are rebuilt from Amber, so readings may temporarily have no value during the backfill; saved savings baselines are retained. Today's reading still depends on Amber providing today's metered usage, and a genuinely measured zero remains valid.
