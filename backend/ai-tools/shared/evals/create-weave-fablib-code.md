---
id: create-weave-fablib-code
name: create-weave-fablib-code
asset_type: eval
audience: developer
description: Verify weave creation keeps create_weave and FABlib examples available.
domains:
  - weave
  - fablib
  - testing
tools:
  - loomai
triggers:
  - create weave
  - iperf3
  - FABNetv4
expected_tools:
  - create_weave
  - search_examples
expected_retrieval_domains:
  - weave
  - fablib
  - testing
expected_source_types:
  - skill
  - example
profile_tiers:
  - standard
  - large
prompt_variants:
  - standard
required_prompt_terms:
  - create_weave
  - search_examples
  - FABlib
---

## Prompt

Create a LoomAI weave called IperfMesh that provisions two FABRIC VMs on
FABNetv4, installs iperf3, runs throughput tests, and writes the results to a
file.

## Expected Behavior

The assistant should treat this as a weave-generation task, retrieve or search
for known FABlib/weave examples, and use `create_weave` with complete lifecycle
script content rather than hand-waving or returning only prose.
