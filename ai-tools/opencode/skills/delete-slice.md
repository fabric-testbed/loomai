name: delete-slice
description: Delete a FABRIC slice (requires user confirmation)
---
Delete a FABRIC slice. **Always requires explicit user confirmation before deleting.**

## Steps

1. **Identify the slice**: If the user named a slice, use it. Otherwise, call
   `fabric_list_slices` to show all slices and ask which one to delete.

2. **Show slice details**: Call `fabric_get_slice(slice_name)` to display what
   will be deleted — nodes, sites, networks, state.

3. **Request confirmation**: Ask the user to confirm deletion. Use clear language:

   "This will permanently delete the slice **<name>** with <N> nodes at <sites>.
   All VMs and data on them will be destroyed. Type 'yes' to confirm."

   **DO NOT proceed without explicit confirmation from the user.**
   If the user says anything other than clear confirmation (yes, confirm, delete it,
   go ahead), do NOT delete. Ask again or cancel.

4. **Delete**: Only after confirmation, call `fabric_delete_slice(slice_name)`.

5. **Report**: Confirm the slice was deleted and resources released.

## Rules

- **NEVER delete without asking first** — even if the user said "delete my slice",
  still show what will be deleted and ask for confirmation.
- If the user asks to delete multiple slices, confirm each one individually.
- If the slice is in StableError state, still confirm before deleting.
- If the slice doesn't exist, report that clearly — don't try to delete.
