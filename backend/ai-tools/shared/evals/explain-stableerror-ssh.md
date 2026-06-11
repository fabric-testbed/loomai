---
id: explain-stableerror-ssh
name: explain-stableerror-ssh
asset_type: eval
audience: developer
description: Verify error explanations retrieve troubleshooting context and keep slice tools available.
domains:
  - fabric
  - troubleshooting
tools:
  - loomai
triggers:
  - StableError
  - SSH fails
  - slice details
expected_tools:
  - get_slice
  - ssh_execute
expected_retrieval_domains:
  - troubleshooting
  - fabric
expected_source_types:
  - curated
  - fabric_ai
profile_tiers:
  - standard
  - large
prompt_variants:
  - loomai-compact
required_prompt_terms:
  - StableError
  - SSH
expected_intent_tool: get_slice
expected_intent_confidence: high
---

## Prompt

Show slice demo details.

## Expected Behavior

The assistant should fetch slice details, surface per-node reservation or error
messages, and explain common StableError and SSH-readiness checks without
claiming that SSH works before nodes are active.
