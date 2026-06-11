/**
 * Module-level terminal session store.
 *
 * Terminal sessions (xterm.js + WebSocket) persist across React component
 * mount/unmount cycles. Sessions are only destroyed when explicitly closed.
 *
 * Local terminals are server-held PTYs: the shell survives a browser reload.
 * On (re)connect we resolve a backend session id for this exact frontend tab,
 * fetch a short-lived attach ticket, and connect to /ws/terminal/attach/{id}.
 * Different local terminal tabs must never attach to the same backend id
 * inside one WebUI, because attaching twice shares one shell view.
 */
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { buildWsUrl } from './wsUrl';
import {
  createTerminal,
  createSshTerminal,
  createChameleonTerminal,
  mintTerminalTicket,
  deleteTerminal,
} from '../api/client';

export const TERM_THEME = {
  background: '#1a1a2e',
  foreground: '#e0e0e0',
  cursor: '#6db3d6',
  selectionBackground: '#3a5a7a',
  black: '#1a1a2e',
  brightBlack: '#4a4a6a',
  red: '#ef5350',
  brightRed: '#ff6b6b',
  green: '#4caf6a',
  brightGreen: '#66cc80',
  yellow: '#ffb74d',
  brightYellow: '#ffd180',
  blue: '#6db3d6',
  brightBlue: '#8ac9ef',
  magenta: '#ba68c8',
  brightMagenta: '#ce93d8',
  cyan: '#4dd0b8',
  brightCyan: '#80e8d0',
  white: '#e0e0e0',
  brightWhite: '#ffffff',
};

export interface TerminalSession {
  term: Terminal;
  ws: WebSocket | null;
  fitAddon: FitAddon;
  containerEl: HTMLDivElement;
  resizeObserver: ResizeObserver;
  // Local (tmux-backed) sessions only:
  backendId?: string;
  closing?: boolean;
  reconnectTimer?: number;
}

const sessions = new Map<string, TerminalSession>();

export function getTerminalSession(id: string): TerminalSession | undefined {
  return sessions.get(id);
}

export function hasTerminalSession(id: string): boolean {
  return sessions.has(id);
}

// --- localStorage mapping: frontend tab id -> backend tmux session id ---

const LS_PREFIX = 'loomai.term.session.';

function storedId(tabId: string): string | null {
  try {
    return localStorage.getItem(LS_PREFIX + tabId);
  } catch {
    return null;
  }
}
function setStoredId(tabId: string, id: string): void {
  try {
    localStorage.setItem(LS_PREFIX + tabId, id);
  } catch {
    /* ignore */
  }
}
function clearStoredId(tabId: string): void {
  try {
    localStorage.removeItem(LS_PREFIX + tabId);
  } catch {
    /* ignore */
  }
}

const localBackendOwners = new Map<string, string>();

function localBackendIdClaimedByOther(backendId: string, tabId: string): boolean {
  const claimedBy = localBackendOwners.get(backendId);
  if (claimedBy && claimedBy !== tabId) {
    const owner = sessions.get(claimedBy);
    if (owner && !owner.closing) return true;
    localBackendOwners.delete(backendId);
  }

  for (const [id, session] of sessions) {
    if (id !== tabId && session.backendId === backendId && !session.closing) {
      localBackendOwners.set(backendId, id);
      return true;
    }
  }
  return false;
}

function claimLocalBackendId(backendId: string, tabId: string): boolean {
  if (localBackendIdClaimedByOther(backendId, tabId)) return false;
  localBackendOwners.set(backendId, tabId);
  return true;
}

function releaseLocalBackendId(tabId: string, backendId?: string): void {
  if (!backendId) return;
  if (localBackendOwners.get(backendId) === tabId) {
    localBackendOwners.delete(backendId);
  }
}

function sendResize(session: TerminalSession): void {
  if (session.ws && session.ws.readyState === WebSocket.OPEN) {
    session.ws.send(
      JSON.stringify({ type: 'resize', cols: session.term.cols, rows: session.term.rows }),
    );
  }
}

/**
 * Resolve a backend session id + attach ticket for a local terminal tab. Each
 * frontend local tab owns its own backend PTY. Old localStorage can contain
 * duplicate mappings from earlier shared-terminal behavior, so claim stored
 * ids before attaching and create a fresh backend session on conflict.
 */
async function resolveLocalSession(tabId: string): Promise<{ id: string; ticket: string }> {
  const existing = storedId(tabId);
  if (existing) {
    if (!claimLocalBackendId(existing, tabId)) {
      clearStoredId(tabId);
    } else {
      try {
        const t = await mintTerminalTicket(existing);
        return { id: existing, ticket: t.ticket };
      } catch {
        releaseLocalBackendId(tabId, existing);
        clearStoredId(tabId); // stale (e.g. session was culled) — fall through
      }
    }
  }

  const meta = await createTerminal('local');
  claimLocalBackendId(meta.id, tabId);
  setStoredId(tabId, meta.id);
  return { id: meta.id, ticket: meta.ticket! };
}

/** Wire WebSocket handlers onto a session. `reconnect` (if given) is invoked
 *  after an unexpected close so tmux-backed terminals re-attach automatically. */
function wireWs(session: TerminalSession, url: string, reconnect?: () => void): void {
  const ws = new WebSocket(url);
  session.ws = ws;

  ws.onopen = () => sendResize(session);
  ws.onmessage = (event) => session.term.write(event.data as string);
  ws.onerror = () => {
    /* surfaced via onclose */
  };
  ws.onclose = () => {
    if (session.closing) return;
    if (reconnect) {
      session.term.writeln('\r\n\x1b[33m[reconnecting…]\x1b[0m');
      session.reconnectTimer = window.setTimeout(() => {
        if (!session.closing) reconnect();
      }, 1000);
    } else {
      session.term.writeln('\r\n\x1b[33mConnection closed.\x1b[0m');
    }
  };
}

function connectLocal(session: TerminalSession, tabId: string): void {
  resolveLocalSession(tabId)
    .then(({ id, ticket }) => {
      if (session.closing) {
        releaseLocalBackendId(tabId, id);
        clearStoredId(tabId);
        deleteTerminal(id).catch(() => {});
        return;
      }
      session.backendId = id;
      const url = buildWsUrl(
        `/ws/terminal/attach/${encodeURIComponent(id)}?ticket=${encodeURIComponent(ticket)}`,
      );
      wireWs(session, url, () => connectLocal(session, tabId));
    })
    .catch((err) => {
      session.term.writeln(`\r\n\x1b[31m[local] connection failed: ${err}\x1b[0m`);
    });
}

/**
 * Resolve a server-held SSH session for a node terminal. The `ssh` runs in a
 * server-side PTY, so reusing the tab's stored session id on reload reattaches
 * to the SAME remote shell (running process intact) — JupyterLab behavior.
 */
async function resolveSshSession(
  tabId: string,
  sshInfo: { sliceName: string; nodeName: string; managementIp: string },
): Promise<{ id: string; ticket: string }> {
  const existing = storedId(tabId);
  if (existing) {
    try {
      const t = await mintTerminalTicket(existing);
      return { id: existing, ticket: t.ticket };
    } catch {
      clearStoredId(tabId); // session was culled/closed server-side — make a new one
    }
  }
  const meta = await createSshTerminal(sshInfo.sliceName, sshInfo.nodeName, sshInfo.managementIp);
  setStoredId(tabId, meta.id);
  return { id: meta.id, ticket: meta.ticket! };
}

function connectSsh(
  session: TerminalSession,
  tabId: string,
  sshInfo: { sliceName: string; nodeName: string; managementIp: string },
): void {
  resolveSshSession(tabId, sshInfo)
    .then(({ id, ticket }) => {
      if (session.closing) return;
      session.backendId = id;
      const url = buildWsUrl(
        `/ws/terminal/attach/${encodeURIComponent(id)}?ticket=${encodeURIComponent(ticket)}`,
      );
      wireWs(session, url, () => connectSsh(session, tabId, sshInfo));
    })
    .catch((err) => {
      session.term.writeln(`\r\n\x1b[31m[terminal] connection failed: ${err}\x1b[0m`);
    });
}

/** Server-held SSH to a Chameleon instance — persists across reload like a
 *  FABRIC node terminal (reattaches to the same remote shell). */
async function resolveChameleonSession(
  tabId: string,
  chameleonInfo: { instanceId: string; site: string },
): Promise<{ id: string; ticket: string }> {
  const existing = storedId(tabId);
  if (existing) {
    try {
      const t = await mintTerminalTicket(existing);
      return { id: existing, ticket: t.ticket };
    } catch {
      clearStoredId(tabId);
    }
  }
  const meta = await createChameleonTerminal(chameleonInfo.instanceId, chameleonInfo.site);
  setStoredId(tabId, meta.id);
  return { id: meta.id, ticket: meta.ticket! };
}

function connectChameleon(
  session: TerminalSession,
  tabId: string,
  chameleonInfo: { instanceId: string; site: string },
): void {
  resolveChameleonSession(tabId, chameleonInfo)
    .then(({ id, ticket }) => {
      if (session.closing) return;
      session.backendId = id;
      const url = buildWsUrl(
        `/ws/terminal/attach/${encodeURIComponent(id)}?ticket=${encodeURIComponent(ticket)}`,
      );
      wireWs(session, url, () => connectChameleon(session, tabId, chameleonInfo));
    })
    .catch((err) => {
      session.term.writeln(`\r\n\x1b[31m[chameleon] connection failed: ${err}\x1b[0m`);
    });
}

export function createTerminalSession(
  id: string,
  type: 'ssh' | 'local' | 'chameleon',
  sshInfo?: { sliceName: string; nodeName: string; managementIp: string },
  chameleonInfo?: { instanceId: string; site: string; name: string },
): TerminalSession {
  const existing = sessions.get(id);
  if (existing) return existing;

  const containerEl = document.createElement('div');
  containerEl.className = 'bp-terminal-container';
  containerEl.style.width = '100%';
  containerEl.style.height = '100%';

  const term = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, monospace",
    theme: { ...TERM_THEME },
  });

  const fitAddon = new FitAddon();
  term.loadAddon(fitAddon);
  term.open(containerEl);

  const session: TerminalSession = {
    term,
    ws: null,
    fitAddon,
    containerEl,
    resizeObserver: undefined as unknown as ResizeObserver,
  };
  sessions.set(id, session);

  // Keystrokes always go to the *current* ws (it may be reassigned on reconnect).
  term.onData((data) => {
    if (session.ws && session.ws.readyState === WebSocket.OPEN) {
      session.ws.send(JSON.stringify({ type: 'input', data }));
    }
  });

  const resizeObserver = new ResizeObserver((entries) => {
    const entry = entries[0];
    if (!entry || entry.contentRect.width === 0 || entry.contentRect.height === 0) return;
    try {
      fitAddon.fit();
      sendResize(session);
    } catch {
      /* ignore resize errors during DOM transitions */
    }
  });
  resizeObserver.observe(containerEl);
  session.resizeObserver = resizeObserver;

  if (type === 'chameleon' && chameleonInfo) {
    term.writeln(
      `\x1b[32m[chameleon] Opening SSH to ${chameleonInfo.name} (${chameleonInfo.site})...\x1b[0m`,
    );
    // Server-held SSH: persists across reload (reattaches to the same remote shell).
    connectChameleon(session, id, { instanceId: chameleonInfo.instanceId, site: chameleonInfo.site });
  } else if (type === 'ssh' && sshInfo) {
    term.writeln(
      `\x1b[36m[terminal] Opening session to ${sshInfo.nodeName} (${sshInfo.managementIp})...\x1b[0m`,
    );
    // Server-held SSH: persists across reload (reattaches to the same remote shell).
    connectSsh(session, id, sshInfo);
  } else {
    // Local terminals are per-tab. They can reattach to their own persisted
    // backend PTY after reload, but never adopt another local tab's PTY.
    term.writeln('\x1b[36m[local] connecting…\x1b[0m');
    connectLocal(session, id);
  }

  return session;
}

export function destroyTerminalSession(id: string): void {
  const session = sessions.get(id);
  if (!session) return;
  session.closing = true;
  if (session.reconnectTimer) {
    clearTimeout(session.reconnectTimer);
  }
  // Explicit close kills the backend session too (≠ reload, which leaves it).
  if (session.backendId) {
    deleteTerminal(session.backendId).catch(() => {});
    releaseLocalBackendId(id, session.backendId);
  }
  clearStoredId(id);
  session.resizeObserver.disconnect();
  if (session.ws) session.ws.close();
  session.term.dispose();
  if (session.containerEl.parentNode) {
    session.containerEl.parentNode.removeChild(session.containerEl);
  }
  sessions.delete(id);
}

export function destroyAllTerminalSessions(): void {
  for (const id of [...sessions.keys()]) {
    destroyTerminalSession(id);
  }
}
