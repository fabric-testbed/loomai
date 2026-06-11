---
id: write-fablib-network-code
name: write-fablib-network-code
asset_type: eval
audience: developer
description: Verify FABlib networking code requests retrieve known-good examples.
domains:
  - fablib
  - networking
tools:
  - loomai
triggers:
  - write FABlib code
  - L2Bridge
  - add_l2network
expected_tools:
  - search_examples
  - write_file
expected_retrieval_domains:
  - fablib
  - networking
expected_source_types:
  - example
profile_tiers:
  - standard
  - large
prompt_variants:
  - standard
required_prompt_terms:
  - search_examples
  - FABlib
---

## Prompt

Write a Python FABlib helper that creates a two-node L2Bridge slice, adds
NIC_Basic interfaces, submits the slice, and prints the assigned interface IPs.

## Expected Behavior

The assistant should search examples first, prefer real FABlib method names
such as `new_slice`, `add_node`, `add_l2network`, and `submit`, and write code
to a file only after grounding on repo examples.
