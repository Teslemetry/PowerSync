<!-- release: v2.12.1413 -->

## What's Changed

**Tesla TOU sync recognizes provider-normalized negative rates**

PowerSync now distinguishes an exact Tesla tariff readback from a confirmed readback where Tesla has rounded non-positive prices to zero. Signed rates remain unchanged in local planning and display, while genuine tariff mismatches continue to fail closed instead of being treated as confirmed.

Update available via HACS
