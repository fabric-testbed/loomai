---
id: extend-chameleon-slice
name: extend-chameleon-slice
asset_type: eval
audience: developer
description: Verify Chameleon slice extension requests keep slice and lease tools available.
domains:
  - chameleon
  - openstack
tools:
  - loomai
triggers:
  - Chameleon slice
  - extend lease
  - compute_haswell
expected_tools:
  - list_chameleon_slices
  - list_chameleon_leases
  - create_chameleon_lease
  - deploy_chameleon_slice
expected_retrieval_domains:
  - chameleon
  - openstack
expected_source_types:
  - curated
  - skill
profile_tiers:
  - standard
  - large
prompt_variants:
  - loomai-extended
required_prompt_terms:
  - Chameleon
  - loomai
---

## Prompt

I have a Chameleon slice at CHI@TACC and need to add one more
`compute_haswell` server for eight hours while keeping SSH reachable. Walk me
through the safe LoomAI workflow.

## Expected Behavior

The assistant should use the Chameleon slice and lease model, retrieve
OpenStack/Chameleon guidance, and avoid treating a Chameleon slice as a native
FABRIC slice.
