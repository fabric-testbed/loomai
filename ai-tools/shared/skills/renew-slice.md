name: renew-slice
description: Check and extend the lease on a FABRIC slice
---
Help the user check slice expiration and renew leases.

1. **Check current lease**:
   - `fabric_get_slice(slice_name)` — look at `lease_end` field
   - If no slice name given, `fabric_list_slices` to show all with lease dates
   - Highlight any slices expiring within 24 hours

2. **Renew**:
   - `fabric_renew_slice(slice_name, days=N)` — extend by N days
   - Maximum renewal is typically 14 days from now
   - If the user doesn't specify days, suggest 14 (the maximum)

3. **Verify**:
   - `fabric_get_slice(slice_name)` — confirm new `lease_end`
   - Report the new expiration date

**Tips:**
- Slices auto-delete when the lease expires — all VMs and data are lost
- Renew proactively; don't wait until the last minute
- If renewal fails with a permission error, the user's token may need refreshing (Configure view)
- Project quotas may limit how far leases can be extended
