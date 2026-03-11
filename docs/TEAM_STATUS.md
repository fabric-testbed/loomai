# Team Status

## Current Goal

(None)

## Active Work

(No active work)

## Completed

- Persist Claude Code config across container rebuilds: backup/restore entire ~/.claude/ dir + ~/.claude.json to .loomai/tools/claude-code/; add Settings panel in Claude Code sidebar to view, edit, save, and reset config files; force IPv4 for Node.js connectivity
- Fix slice delete race condition: slices no longer pop back to StableOK after deletion — polling preserves Closing/Dead state until FABRIC confirms (2-min timeout)
- Remove all "builtin" artifact references from frontend, backend AI docs, and both ai-tools/ copies

- Orchestrated run: ▶ Run on deploy+run weaves now deploys first, waits for completion, then auto-starts run.sh — full experiment lifecycle in one click
- Unified play button color: all ▶ buttons use primary blue (#5798bc) regardless of mode (Load/Deploy/Run)
- Transport controls on weave cards: ▶ Play, ■ Stop, ↺ Reset always visible with enable/disable states
- Artifacts view: weave cards show "Open in Slices" instead of Load/Deploy/Run
- Running weave indicator + reattach: LibrariesPanel now shows "running" badge on weaves with active background runs, plus "View Output" / "Last Output" button to open the log tab in BottomPanel
- Backend/Frontend: Add tool install progress popup with SSE streaming

## Blockers

(No blockers)
