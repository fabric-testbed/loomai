"""Allow running as ``python -m loomai_cli``.

Intercepts special commands (/ask, ?, /model) before Click processes them.
"""
import os
import sys


def main():
    args = sys.argv[1:]

    # Handle: loomai /ask <question> or loomai ? <question>
    if args and args[0] in ("/ask", "?"):
        question = " ".join(args[1:])
        if not question:
            print("Usage: loomai /ask <question>  or  loomai ? <question>")
            sys.exit(1)
        # Route to ai chat one-shot
        sys.argv = [sys.argv[0], "ai", "chat", question]

    # Handle: loomai <command> help → loomai help <command>
    # (so "loomai slices help" works like "loomai help slices")
    elif len(args) >= 2 and args[-1] == "help" and args[0] != "help":
        sys.argv = [sys.argv[0], "help"] + args[:-1]

    # Handle: loomai /model or loomai /model <name>
    elif args and args[0] == "/model":
        if len(args) > 1:
            # Direct set — route to shell model command
            from loomai_cli.client import Client
            from loomai_cli.shell import _handle_model
            url = os.environ.get("LOOMAI_URL", "http://localhost:8000")
            client = Client(url)
            _handle_model(args[1:], client)
            sys.exit(0)
        else:
            # Interactive picker
            from loomai_cli.client import Client
            from loomai_cli.shell import _handle_model
            url = os.environ.get("LOOMAI_URL", "http://localhost:8000")
            client = Client(url)
            _handle_model([], client)
            sys.exit(0)

    from loomai_cli.main import cli
    cli()


main()
