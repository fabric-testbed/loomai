"""Interactive LoomAI shell with tab completion, context selection, and AI assistant.

Enter with `loomai` (no args). Features:
- Built-in tab completion for all commands
- Context selection: `use slice my-exp`, `use node node1`, `use site RENC`
- AI assistant: `/ask <question>` or `? <question>`
- Model picker: `/model` (interactive) or `/model <name>` (direct set)
- Command shortcuts: `ls` = `slices list`
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from typing import Optional

import click

from loomai_cli.client import Client
from loomai_cli.completions import _fetch_cached


# ---------------------------------------------------------------------------
# Shell tab completion
# ---------------------------------------------------------------------------

# Top-level commands and their subcommands
_SHELL_COMMANDS: dict[str, list[str]] = {
    "slices": ["list", "show", "create", "delete", "submit", "modify",
               "validate", "renew", "refresh", "slivers", "wait", "clone",
               "export", "import", "archive"],
    "nodes": ["add", "update", "remove"],
    "networks": ["add", "update", "remove"],
    "components": ["add", "remove"],
    "sites": ["list", "show", "hosts", "find"],
    "facility-ports": ["list", "add", "remove"],
    "weaves": ["list", "show", "load", "run", "stop", "logs", "runs"],
    "boot-config": ["show", "set", "run", "log"],
    "artifacts": ["list", "search", "show", "get", "publish", "update",
                  "delete", "tags", "versions", "push-version", "delete-version"],
    "recipes": ["list", "show", "run"],
    "vm-templates": ["list", "show"],
    "monitor": ["enable", "disable", "status", "metrics"],
    "config": ["show", "settings"],
    "projects": ["list", "switch"],
    "keys": ["list", "generate"],
    "ai": ["chat", "models", "agents"],
    "ssh": [],
    "exec": [],
    "scp": [],
    "rsync": [],
    "images": [],
    "component-models": [],
    "completions": [],
}

# Shell-only commands (not CLI subcommands)
_SHELL_BUILTINS = ["use", "exit", "quit", "clear", "context",
                   "ls", "sites", "weaves", "recipes", "images",
                   "models", "slivers", "help", "?", "/ask", "/model"]

# Map (command, subcommand) → completion type for the first argument
_ARG_COMPLETIONS: dict[tuple[str, str | None], str] = {
    # slices subcommands that take a slice name
    ("slices", "show"): "slice", ("slices", "delete"): "slice",
    ("slices", "submit"): "slice", ("slices", "modify"): "slice",
    ("slices", "validate"): "slice",
    ("slices", "renew"): "slice", ("slices", "refresh"): "slice",
    ("slices", "slivers"): "slice", ("slices", "wait"): "slice",
    ("slices", "clone"): "slice", ("slices", "export"): "slice",
    ("slices", "create"): "slice", ("slices", "archive"): "slice",
    # nodes/networks/components take slice name first
    ("nodes", "add"): "slice", ("nodes", "update"): "slice",
    ("nodes", "remove"): "slice",
    ("networks", "add"): "slice", ("networks", "update"): "slice",
    ("networks", "remove"): "slice",
    ("components", "add"): "slice", ("components", "remove"): "slice",
    ("facility-ports", "add"): "slice", ("facility-ports", "remove"): "slice",
    # boot-config takes slice
    ("boot-config", "show"): "slice", ("boot-config", "set"): "slice",
    ("boot-config", "run"): "slice", ("boot-config", "log"): "slice",
    # standalone commands
    ("ssh", None): "slice", ("exec", None): "slice",
    ("scp", None): "slice", ("rsync", None): "slice",
    # weaves
    ("weaves", "show"): "weave", ("weaves", "load"): "weave",
    ("weaves", "run"): "weave",
    # sites
    ("sites", "show"): "site", ("sites", "hosts"): "site",
    # recipes
    ("recipes", "show"): "recipe", ("recipes", "run"): "recipe",
    # use command
    ("use", None): "use_type",
}

_USE_TYPES = ["slice", "node", "site", "weave"]

_completions_cache: list[str] = []


def _get_completions_for_type(comp_type: str) -> list[str]:
    """Fetch completions by type, reusing the cache from completions.py."""
    if comp_type == "slice":
        return _fetch_cached("slices", "/slices?max_age=30")
    elif comp_type == "site":
        return _fetch_cached("sites", "/sites?max_age=300")
    elif comp_type == "weave":
        return _fetch_cached("templates", "/templates")
    elif comp_type == "recipe":
        return _fetch_cached("recipes", "/recipes")
    elif comp_type == "use_type":
        return _USE_TYPES
    return []


def _shell_completer(text: str, state: int) -> str | None:
    """Readline completer for the interactive shell."""
    global _completions_cache

    if state == 0:
        import readline
        buf = readline.get_line_buffer()
        try:
            parts = shlex.split(buf)
        except ValueError:
            parts = buf.split()

        # If buffer ends with space, user is starting a new token
        completing_new = buf.endswith(" ") and buf.strip()
        if completing_new:
            parts.append("")

        if len(parts) <= 1:
            # Complete first word — commands + builtins
            prefix = text.lower()
            all_cmds = list(_SHELL_COMMANDS.keys()) + _SHELL_BUILTINS
            _completions_cache = sorted(set(
                c for c in all_cmds if c.startswith(prefix)
            ))
        elif len(parts) == 2:
            cmd = parts[0]
            prefix = text.lower()
            if cmd in _SHELL_COMMANDS and _SHELL_COMMANDS[cmd]:
                # Complete subcommand
                _completions_cache = [
                    s for s in _SHELL_COMMANDS[cmd] if s.startswith(prefix)
                ]
            elif cmd == "use":
                _completions_cache = [
                    t for t in _USE_TYPES if t.startswith(prefix)
                ]
            else:
                # First arg for standalone commands
                comp_type = _ARG_COMPLETIONS.get((cmd, None), "")
                if comp_type:
                    names = _get_completions_for_type(comp_type)
                    _completions_cache = [
                        n for n in names if n.lower().startswith(prefix)
                    ]
                else:
                    _completions_cache = []
        elif len(parts) >= 3:
            cmd = parts[0]
            sub = parts[1]
            prefix = text.lower()
            # Complete argument after subcommand
            comp_type = _ARG_COMPLETIONS.get((cmd, sub), "")
            if comp_type and len(parts) == 3:
                names = _get_completions_for_type(comp_type)
                _completions_cache = [
                    n for n in names if n.lower().startswith(prefix)
                ]
            elif cmd == "use" and len(parts) == 3:
                # use <type> <name> — complete based on type
                use_type = sub
                if use_type == "slice":
                    names = _get_completions_for_type("slice")
                elif use_type == "site":
                    names = _get_completions_for_type("site")
                elif use_type == "weave":
                    names = _get_completions_for_type("weave")
                else:
                    names = []
                _completions_cache = [
                    n for n in names if n.lower().startswith(prefix)
                ]
            else:
                _completions_cache = []
        else:
            _completions_cache = []

    if state < len(_completions_cache):
        return _completions_cache[state]
    return None


# Context state
_context = {
    "slice": "",
    "node": "",
    "site": "",
    "weave": "",
    "model": "",
}

# Command shortcuts
SHORTCUTS = {
    "ls": ["slices", "list"],
    "sites": ["sites", "list"],
    "weaves": ["weaves", "list"],
    "recipes": ["recipes", "list"],
    "images": ["images"],
    "models": ["ai", "models"],
    "slivers": None,  # Special — uses context slice
}


def _get_prompt() -> str:
    """Build the shell prompt showing current context."""
    parts = []
    if _context["slice"]:
        if _context["node"]:
            parts.append(f"{_context['slice']}/{_context['node']}")
        else:
            parts.append(_context["slice"])
    if _context["site"] and not _context["slice"]:
        parts.append(_context["site"])
    ctx_str = f" [{'/'.join(parts)}]" if parts else ""
    model_str = f" ({_context['model']})" if _context["model"] else ""
    return f"loomai{ctx_str}{model_str} > "


def _load_config() -> dict:
    """Load persisted config from ~/.loomai/config."""
    config_path = os.path.expanduser("~/.loomai/config")
    if os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_config(data: dict) -> None:
    """Save config to ~/.loomai/config."""
    config_dir = os.path.expanduser("~/.loomai")
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, "config"), "w") as f:
        json.dump(data, f, indent=2)


def _handle_use(args: list[str], client: Client) -> None:
    """Handle `use <type> <name>` commands."""
    if len(args) < 2:
        click.echo("Usage: use <slice|node|site|weave> <name>")
        click.echo(f"Current: slice={_context['slice']} node={_context['node']} site={_context['site']} weave={_context['weave']}")
        return
    obj_type = args[0].lower()
    name = args[1]
    if obj_type in _context:
        _context[obj_type] = name
        click.echo(f"Set {obj_type} = {name}")
    else:
        click.echo(f"Unknown type: {obj_type}. Use: slice, node, site, weave")


def _handle_show_context() -> None:
    """Show current context."""
    for k, v in _context.items():
        if v:
            click.echo(f"  {k}: {v}")
    if not any(_context.values()):
        click.echo("  (no context set)")


def _handle_clear_context() -> None:
    """Clear all context."""
    for k in _context:
        _context[k] = ""
    click.echo("Context cleared.")


def _sync_model_to_backend(client, model: str) -> None:
    """Sync the selected model to the backend shared config."""
    try:
        client.put("/ai/models/default", json={"model": model})
    except Exception:
        pass  # Best-effort — backend may be unavailable


def _handle_model(args: list[str], client: Client) -> None:
    """Handle `/model` — list or set model."""
    if args:
        # Direct set
        _context["model"] = args[0]
        config = _load_config()
        config["model"] = args[0]
        _save_config(config)
        _sync_model_to_backend(client, args[0])
        click.echo(f"Model set to: {args[0]}")
        return

    # Show current model (check context first, then local config, then backend)
    current_model = _context.get("model", "")
    if not current_model:
        config = _load_config()
        current_model = config.get("model", "")
        if current_model:
            _context["model"] = current_model
    if not current_model:
        try:
            data = client.get("/ai/models/default")
            current_model = data.get("default", "")
        except Exception:
            pass
    if current_model:
        click.echo(f"Current model: {current_model}")
    else:
        click.echo("Current model: (none — using server default)")
    click.echo()

    # Interactive picker — fetch models and show list
    try:
        data = client.get("/ai/models")
        models = []
        for m in data.get("fabric", []):
            label = m["id"]
            ctx = m.get("context_length")
            tier = m.get("tier", "")
            badges = []
            if ctx:
                badges.append("128K+" if ctx >= 100000 else "32K" if ctx >= 30000 else "16K" if ctx >= 12000 else "8K")
            if tier == "compact":
                badges.append("fast")
            elif tier == "large":
                badges.append("powerful")
            if m.get("supports_tools"):
                badges.append("tools")
            badge_str = f" [{', '.join(badges)}]" if badges else ""
            is_default = m["id"] == data.get("default", "")
            star = " \u2605" if is_default else ""
            healthy = m.get("healthy", True)
            unavail = " (unavailable)" if not healthy else ""
            models.append((m["id"], f"{label}{badge_str}{star}{unavail}", healthy))

        for m in data.get("nrp", []):
            healthy = m.get("healthy", True)
            unavail = " (unavailable)" if not healthy else ""
            models.append((f"nrp:{m['id']}", f"nrp:{m['id']}{unavail}", healthy))

        if not models:
            click.echo("No models available.")
            return

        # Simple list with numbering (prompt_toolkit picker is optional)
        click.echo("Available models:")
        for i, (mid, label, healthy) in enumerate(models):
            marker = "  " if healthy else "  "
            current = " <<<" if mid == _context.get("model") else ""
            click.echo(f"  {i + 1}. {label}{current}")

        click.echo()
        choice = click.prompt("Select model (number or name, Enter to keep current)", default="", show_default=False)
        if not choice:
            click.echo("Keeping current model.")
            return
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                selected = models[idx][0]
            else:
                click.echo("Invalid number.")
                return
        except ValueError:
            selected = choice

        _context["model"] = selected
        config = _load_config()
        config["model"] = selected
        _save_config(config)
        _sync_model_to_backend(client, selected)
        click.echo(f"Model set to: {selected}")

    except Exception as e:
        click.echo(f"Error fetching models: {e}")


def _handle_ask(question: str, client: Client) -> None:
    """Handle `/ask <question>` or `? <question>` — AI assistant."""
    if not question.strip():
        click.echo("Usage: /ask <question> or ? <question>")
        return

    # Add context info to the question
    context_info = ""
    if _context["slice"]:
        context_info += f" (current slice: {_context['slice']})"
    if _context["node"]:
        context_info += f" (current node: {_context['node']})"

    model = _context.get("model") or ""

    try:
        import httpx
        body = {
            "messages": [{"role": "user", "content": question + context_info}],
            "model": model,
        }
        with httpx.stream("POST", f"{client.base_url}/api/ai/chat/stream",
                           json=body, timeout=60.0) as resp:
            if resp.status_code >= 400:
                click.echo(f"Error: {resp.read().decode()[:200]}")
                return
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                    if "content" in data and data["content"]:
                        click.echo(data["content"], nl=False)
                    elif "tool_call" in data:
                        tc = data["tool_call"]
                        click.echo(f"\n[Executing: {tc['name']}...]", err=True)
                    elif "warning" in data:
                        click.echo(f"\n\u26A0 {data['warning']}", err=True)
                    elif "error" in data:
                        click.echo(f"\nError: {data['error']}", err=True)
                except json.JSONDecodeError:
                    continue
        click.echo()  # Final newline
    except Exception as e:
        click.echo(f"AI request failed: {e}")


def _inject_context(args: list[str]) -> list[str]:
    """Inject context defaults into command args."""
    if not args:
        return args

    # For commands that take slice_name as first arg after the subcommand
    slice_commands = {"show", "delete", "submit", "modify", "validate", "renew",
                      "refresh", "slivers", "wait", "clone", "export", "archive"}
    if len(args) >= 1 and args[0] == "slices" and len(args) >= 2 and args[1] in slice_commands:
        if len(args) == 2 and _context["slice"]:
            args.append(_context["slice"])

    # ssh with context
    if args[0] == "ssh" and _context["slice"]:
        if len(args) == 1 and _context["node"]:
            args.extend([_context["slice"], _context["node"]])
        elif len(args) == 2:
            # ssh <node_or_command> — inject slice before
            args.insert(1, _context["slice"])

    # exec with context
    if args[0] == "exec" and _context["slice"]:
        if len(args) >= 2 and not args[1].startswith("-"):
            # exec <command> — inject slice
            args.insert(1, _context["slice"])

    return args


def run_shell(url: str, fmt: str = "table") -> None:
    """Run the interactive LoomAI shell."""
    client = Client(url)

    # Load saved model preference, or fetch default from backend
    config = _load_config()
    if config.get("model"):
        _context["model"] = config["model"]
    else:
        try:
            data = client.get("/ai/models/default")
            default_model = data.get("default", "")
            if default_model:
                source = data.get("source", "fabric")
                mid = f"nrp:{default_model}" if source == "nrp" else default_model
                _context["model"] = mid
                config["model"] = mid
                _save_config(config)
        except Exception:
            pass  # No backend or no models — user can set later

    # History file — readline gives us up/down arrow navigation
    history_path = os.path.expanduser("~/.loomai/history")
    os.makedirs(os.path.dirname(history_path), exist_ok=True)
    try:
        import readline
        readline.set_history_length(1000)
        try:
            readline.read_history_file(history_path)
        except FileNotFoundError:
            pass
        # Enable tab completion
        readline.set_completer(_shell_completer)
        readline.set_completer_delims(" ")
        # Handle macOS libedit vs GNU readline
        if getattr(readline, "__doc__", "") and "libedit" in (readline.__doc__ or ""):
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")
    except ImportError:
        readline = None  # type: ignore[assignment]

    click.echo("LoomAI Interactive Shell")
    click.echo("Type commands, /ask or ? for AI, /model to change model, exit to quit.")
    click.echo()

    while True:
        try:
            line = input(_get_prompt()).strip()
        except (EOFError, KeyboardInterrupt):
            click.echo("\nBye!")
            if readline:
                readline.write_history_file(history_path)
            break

        if not line:
            continue

        # Exit
        if line.lower() in ("exit", "quit", "q"):
            click.echo("Bye!")
            if readline:
                readline.write_history_file(history_path)
            break

        # Save history after each command
        if readline:
            readline.write_history_file(history_path)

        # AI assistant
        if line.startswith("? ") or line.startswith("/ask "):
            question = line[2:] if line.startswith("? ") else line[5:]
            _handle_ask(question, client)
            continue

        if line == "?":
            click.echo("Usage: ? <question> — ask the AI assistant")
            continue

        # Model command
        if line.startswith("/model"):
            args = line[6:].strip().split() if len(line) > 6 else []
            _handle_model(args, client)
            continue

        # Use command
        if line.startswith("use "):
            _handle_use(line[4:].split(), client)
            continue

        # Show/clear context
        if line in ("show context", "context"):
            _handle_show_context()
            continue
        if line in ("clear context", "clear"):
            _handle_clear_context()
            continue

        # Shortcuts
        if line in SHORTCUTS and SHORTCUTS[line] is not None:
            line = " ".join(SHORTCUTS[line])
        elif line == "slivers" and _context["slice"]:
            line = f"slices slivers {_context['slice']}"

        # Parse and inject context
        try:
            args = shlex.split(line)
        except ValueError:
            args = line.split()

        args = _inject_context(args)

        # Run as loomai subcommand
        from loomai_cli.main import cli
        try:
            ctx = cli.make_context("loomai", ["--url", url, "--format", fmt] + args,
                                    resilient_parsing=False)
            with ctx:
                cli.invoke(ctx)
        except click.exceptions.Exit:
            pass
        except click.exceptions.UsageError as e:
            click.echo(f"Error: {e}")
        except SystemExit:
            pass
        except Exception as e:
            click.echo(f"Error: {e}")
