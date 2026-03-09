#!/usr/bin/env python3
"""FabChat — FABRIC-aware AI chat REPL using the OpenAI-compatible API."""

import os
import sys

try:
    from openai import OpenAI
except ImportError:
    print("Error: 'openai' package not installed. Run: pip install openai>=1.0", file=sys.stderr)
    sys.exit(1)

SYSTEM_PROMPT = """\
You are FabChat, an expert AI assistant for the FABRIC testbed research infrastructure.

You specialize in:
- FABLib (fabrictestbed-extensions): Creating and managing slices, nodes, networks, components
- Slice design: Topologies, site selection, resource sizing, network configuration (L2/L3, FABNetv4/v6)
- FABRIC sites and resources: Available sites, GPU/FPGA/SmartNIC availability, host constraints
- Network experiments: Setting up measurements, iperf, routing, VLAN stitching, facility ports
- Troubleshooting: Debugging slice failures, SSH connectivity, resource allocation errors
- The FABRIC Web GUI (fabric-webgui): Template system, boot configs, site mapping, monitoring

When providing code examples, use FABLib conventions:
```python
from fabrictestbed_extensions.fablib.fablib import FablibManager
fablib = FablibManager()
```

Be concise and practical. Provide working code snippets when helpful.\
"""


def main():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    api_base = os.environ.get("OPENAI_API_BASE", "https://ai.fabric-testbed.net/v1")

    if not api_key:
        print("\033[31mError: OPENAI_API_KEY not set. Configure your AI API key in Settings.\033[0m")
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url=api_base)
    model = os.environ.get("FABCHAT_MODEL", "gpt-4o")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("\033[36m" + "=" * 60)
    print("  FabChat — FABRIC AI Assistant")
    print(f"  Model: {model} via {api_base}")
    print("  Type 'exit' or 'quit' to end the session.")
    print("=" * 60 + "\033[0m\n")

    while True:
        try:
            user_input = input("\033[32mYou:\033[0m ")
        except (EOFError, KeyboardInterrupt):
            print("\n\033[36mGoodbye!\033[0m")
            break

        if user_input.strip().lower() in ("exit", "quit"):
            print("\033[36mGoodbye!\033[0m")
            break

        if not user_input.strip():
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            print("\033[35mFabChat:\033[0m ", end="", flush=True)
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
            )
            full_response = ""
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    print(delta.content, end="", flush=True)
                    full_response += delta.content
            print()
            messages.append({"role": "assistant", "content": full_response})
        except Exception as e:
            print(f"\n\033[31mError: {e}\033[0m")


if __name__ == "__main__":
    main()
