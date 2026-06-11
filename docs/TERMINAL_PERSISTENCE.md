# Persistent Terminals + WebSocket Auth

Status: implemented 2026-06-10. Replaces the socket-bound PTY model so terminals
survive browser reload / reconnect from another browser or machine, and closes the
unauthenticated-WebSocket RCE at the same time.

> **Implementation note (supersedes the tmux design below).** The container
> (local + AI) terminals use the **in-process JupyterLab/terminado model**, not
> tmux. `terminal_sessions.py` is an in-process PTY registry: the server owns the
> PTY (`master_fd` + child process), a non-blocking reader broadcasts output to
> all attached client queues and into a bounded scrollback buffer, and
> `/ws/terminal/attach/{id}` replays the buffer then streams. Detach (disconnect)
> keeps the shell; it does not survive a backend restart. This was chosen over
> tmux after tmux caused garbled rendering, CLI-looking chrome (status bar), and
> no VM-side persistence. The auth/ticket/route/frontend design below is intact;
> only the session *backing* changed from tmux to in-process. **SSH/Chameleon
> terminals currently use a plain shell (no persistence yet); Phase 2 will hold
> the SSH channel server-side the same way — also without tmux.** The sections
> below describe the original tmux design and are retained for history.

## Problem

Today the PTY lifetime is bolted to the WebSocket. `container_terminal_ws`
(`backend/app/routes/terminal.py:469`), `ai_terminal_ws`
(`ai_terminal.py:2123`), and the SSH variants all `pty.openpty()` +
`subprocess.Popen()` on connect and `proc.terminate()` in `finally` on any
disconnect (`terminal.py:540`). The frontend `terminalStore.ts` keeps the
xterm+WS alive across React mount/unmount (tab switches) but a full page reload
destroys the SPA → `ws.close()` → backend kills the shell. Nothing is
server-durable, and the WS handshake bypasses `AuthMiddleware` (Starlette
`BaseHTTPMiddleware` only runs for http scope), so any connector gets a free
root shell.

## Approach (chosen): tmux-backed sessions + signed attach tickets

The server no longer owns the shell directly — **tmux does** (already installed,
`Dockerfile:22`). The WebSocket's PTY merely runs `tmux attach`. The shell is a
child of the tmux server (a separate process), so it survives browser reload AND
a backend process restart; only a full container recreate loses it. tmux replays
pane scrollback on attach for free, and multiple attaches to one session share
the view (reconnect-from-another-machine works).

### Session naming
- local container shell: tmux session `loomai_local_<id>`
- AI tool: `loomai_ai_<tool>_<id>`
- SSH-to-VM (Stage 3): tmux runs **on the VM** via `ssh -t '... tmux new -A -s loomai_<node>'`
  → survives backend restart and network blips; standard practice.

### HTTP control plane (authenticated by existing AuthMiddleware)
- `POST /api/terminals` `{type, tool?, slice?, node?, cwd?}` →
  ensures the tmux session exists (`tmux new-session -d -A -s <name> <cmd>`),
  returns `{ session_id, ticket }`.
- `GET /api/terminals` → list live sessions (so a fresh client on another machine
  can discover and reattach). Returns id, type, label, created, last_attached.
- `POST /api/terminals/{id}/ticket` → mint a fresh attach ticket for an existing
  session (reload path: client kept the id, needs a new ticket).
- `DELETE /api/terminals/{id}` → `tmux kill-session`.

### Attach data plane
- `WS /ws/terminal/attach/{session_id}?ticket=<t>` →
  **validate ticket (or `loomai_session` cookie) BEFORE `await websocket.accept()`**;
  reject with close code 1008 otherwise. Then PTY-exec `tmux -u attach -t <name>`,
  pump bytes both ways, forward resize via TIOCSWINSZ. On WS close, kill only the
  `tmux attach` client process — the tmux session (and shell) keeps running.

### Attach ticket
- `mint_ticket(session_id) -> "<session_id>.<exp>.<hmac>"`, exp ~60s, single-use
  (nonce tracked in an in-memory set with TTL). Signed with the **persistent**
  server secret below. Bound to session_id so it can't be replayed against another.
- WS accepts either a valid ticket OR a valid `loomai_session` cookie (so the
  same-origin browser flow works without a ticket round-trip if desired).

### Persistent server secret (new, also fixes a UX papercut)
`auth._get_session_secret()` is currently `os.urandom(32)` per process, so every
backend restart invalidates all login cookies. For reattach-after-restart to work
and to stop logging users out on restart, persist the secret to
`{STORAGE_DIR}/.loomai/session_secret` (0600, generated once). Use it for both the
login session cookie and the attach ticket HMAC.

### Cull / lifecycle
- Background task: `tmux kill-session` for sessions with **no attached client**
  and idle (no activity / no attach) > N hours. Cap total sessions per type.
- Sessions are listed/owned single-user (this app is single-user per container);
  in K8s each user has their own pod, so no cross-user concern.

## Security outcome
- The WS no longer **spawns** anything — it only **attaches** to a session created
  by an authenticated `POST`. Unauthenticated connect with no/unknown id → closed.
- Real auth enforced before `accept()` via ticket/cookie → closes the RCE.
- nginx: still must put `/jupyter/`, `/aider/`, `/opencode/`, `/tunnel/` behind
  `auth_request` (separate audit item) — this change does not cover those.

## Staging
1. **Foundation** (this PR slice): persistent secret; `terminal_auth.py`
   (ticket mint/verify); `terminal_sessions.py` (tmux manager); unit tests. No
   route/UI change yet — importable + tested in isolation.
2. **Local terminal vertical slice**: `POST/GET/DELETE /api/terminals`, new attach
   WS, frontend `terminalStore` reattach (persist session id in localStorage,
   fetch a ticket on (re)connect, list+reattach on cold load). Keep old
   `/ws/terminal/container` until the UI is migrated, then remove.
3. **AI terminals**: extend manager to launch AI tools inside tmux (env via a
   sourced tmpfile, never on the argv to avoid `ps` leakage). Migrate
   `TerminalCompanionView`.
4. **SSH/Chameleon terminals**: tmux-on-VM attach pattern.
5. **Cull task + remove legacy spawn-on-connect endpoints.** Add regression test:
   unauthenticated `/ws/terminal/attach/x` is rejected before accept.

## Notes / gotchas
- tmux must use a stable socket dir owned by the run user; set `tmux -L loomai`
  (dedicated server) so we don't collide with user tmux. Server survives as long
  as the container PID namespace does.
- Initial tmux pane size: create with `-x/-y` or resize on first attach; xterm
  sends a resize on open already.
- Multiple simultaneous attaches share one pane (tmux clamps to smallest size).
  Acceptable / desirable for hand-off; document it.
- `tmux new-session -A` = attach-or-create, race-safe for the reload path.
