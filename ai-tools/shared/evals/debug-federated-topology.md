---
id: debug-federated-topology
name: debug-federated-topology
asset_type: eval
audience: developer
description: Verify federated topology debugging keeps composite/federated tools available.
domains:
  - federated
  - troubleshooting
tools:
  - loomai
triggers:
  - federated topology
  - missing member
  - cross-testbed
expected_tools:
  - list_composite_slices
  - get_composite_slice
expected_retrieval_domains:
  - federated
  - troubleshooting
expected_source_types:
  - curated
  - example
profile_tiers:
  - standard
  - large
prompt_variants:
  - standard
required_prompt_terms:
  - Federated
  - topology
---

## Prompt

A Federated Slice topology still shows the old FABRIC member after submit and
the Chameleon member is missing from the graph. What should I inspect first?

## Expected Behavior

The assistant should retrieve federated/composite graph-refresh guidance,
inspect the federated slice record before blaming FABRIC, and explain provider
member ownership clearly.
