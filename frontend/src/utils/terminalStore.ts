/**
 * Module-level terminal session store.
 * Terminal sessions (xterm.js + WebSocket) persist across React component
 * mount/unmount cycles. Sessions are only destroyed when explicitly closed.
 */
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { buildWsUrl } from './wsUrl';

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
  ws: WebSocket;
  fitAddon: FitAddon;
  containerEl: HTMLDivElement;
  resizeObserver: ResizeObserver;
}

const sessions = new Map<string, TerminalSession>();

export function getTerminalSession(id: string): TerminalSession | undefined {
  return sessions.get(id);
}

export function hasTerminalSession(id: string): boolean {
  return sessions.has(id);
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

  let wsUrl: string;
  if (type === 'chameleon' && chameleonInfo) {
    term.writeln(
      `\x1b[32m[chameleon] Opening SSH to ${chameleonInfo.name} (${chameleonInfo.site})...\x1b[0m`,
    );
    wsUrl = buildWsUrl(
      `/ws/terminal/chameleon/${encodeURIComponent(chameleonInfo.instanceId)}?site=${encodeURIComponent(chameleonInfo.site)}`,
    );
  } else if (type === 'ssh' && sshInfo) {
    term.writeln(
      `\x1b[36m[terminal] Opening session to ${sshInfo.nodeName} (${sshInfo.managementIp})...\x1b[0m`,
    );
    wsUrl = buildWsUrl(
      `/ws/terminal/${encodeURIComponent(sshInfo.sliceName)}/${encodeURIComponent(sshInfo.nodeName)}`,
    );
  } else {
    term.writeln('\x1b[36m[local] Opening shell...\x1b[0m');
    wsUrl = buildWsUrl('/ws/terminal/container');
  }

  const ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
  };
  ws.onmessage = (event) => {
    term.write(event.data);
  };
  ws.onerror = () => {
    term.writeln('\r\n\x1b[31mWebSocket error.\x1b[0m');
  };
  ws.onclose = () => {
    term.writeln('\r\n\x1b[33mConnection closed.\x1b[0m');
  };

  term.onData((data) => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'input', data }));
    }
  });

  const resizeObserver = new ResizeObserver((entries) => {
    const entry = entries[0];
    if (!entry || entry.contentRect.width === 0 || entry.contentRect.height === 0) return;
    try {
      fitAddon.fit();
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
      }
    } catch {
      /* ignore resize errors during DOM transitions */
    }
  });
  resizeObserver.observe(containerEl);

  const session: TerminalSession = { term, ws, fitAddon, containerEl, resizeObserver };
  sessions.set(id, session);
  return session;
}

export function destroyTerminalSession(id: string): void {
  const session = sessions.get(id);
  if (!session) return;
  session.resizeObserver.disconnect();
  session.ws.close();
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
