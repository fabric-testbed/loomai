/**
 * Unit tests for the persistent terminal store (today's tmux/server-held-PTY
 * reattach logic). We drive the public API (createTerminalSession /
 * destroyTerminalSession) and assert how it resolves a backend session id:
 *
 *   - fresh per-tab terminal           -> POST create, store id in localStorage
 *   - reload with a stored id          -> mint a ticket and REUSE (no create)
 *   - stored id went stale             -> clear it and create a new one
 *   - duplicate stored ids             -> only one tab reuses it; others get fresh sessions
 *   - explicit close                   -> DELETE the backend session + clear storage
 *
 * xterm, the WebSocket, ResizeObserver and the API client are all stubbed so
 * the test exercises only the resolve/persist logic.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// --- module mocks (hoisted) ---
vi.mock('../api/client', () => ({
  createTerminal: vi.fn(),
  createSshTerminal: vi.fn(),
  createChameleonTerminal: vi.fn(),
  listTerminals: vi.fn(),
  mintTerminalTicket: vi.fn(),
  deleteTerminal: vi.fn(),
}));
vi.mock('../utils/wsUrl', () => ({ buildWsUrl: (p: string) => `ws://mock${p}` }));
vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() {} } }));
vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    cols = 80; rows = 24;
    loadAddon() {}
    open() {}
    onData() {}
    write() {}
    writeln() {}
    refresh() {}
    dispose() {}
  },
}));

import * as api from '../api/client';
import {
  createTerminalSession,
  destroyTerminalSession,
  destroyAllTerminalSessions,
  hasTerminalSession,
} from '../utils/terminalStore';

const LS = (tabId: string) => `loomai.term.session.${tabId}`;

let createdSockets: FakeWebSocket[];

class FakeWebSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSING = 2;
  static CLOSED = 3;
  url: string;
  readyState = FakeWebSocket.OPEN;
  onopen: ((e?: unknown) => void) | null = null;
  onclose: ((e?: unknown) => void) | null = null;
  onmessage: ((e?: unknown) => void) | null = null;
  onerror: ((e?: unknown) => void) | null = null;
  closed = false;
  constructor(url: string) {
    this.url = url;
    createdSockets.push(this);
  }
  send() {}
  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  createdSockets = [];
  localStorage.clear();
  vi.clearAllMocks();
  (globalThis as any).WebSocket = FakeWebSocket;
  (globalThis as any).ResizeObserver = class {
    observe() {}
    disconnect() {}
    unobserve() {}
  };
  // Safe defaults; individual tests override.
  vi.mocked(api.deleteTerminal).mockResolvedValue({ ok: true });
  vi.mocked(api.listTerminals).mockResolvedValue([]);
});

afterEach(() => {
  destroyAllTerminalSessions();
});

const lastSocketUrl = () => createdSockets[createdSockets.length - 1]?.url;

describe('local terminal session resolution', () => {
  it('creates a backend session on first open and stores the mapping', async () => {
    vi.mocked(api.createTerminal).mockResolvedValue({
      id: 'be-1', type: 'local', label: 'local', created: 1, ticket: 'be-1.tkt',
    } as any);

    createTerminalSession('term-A', 'local');

    await vi.waitFor(() => expect(createdSockets.length).toBe(1));
    expect(api.createTerminal).toHaveBeenCalledTimes(1);
    expect(api.listTerminals).not.toHaveBeenCalled();
    expect(localStorage.getItem(LS('term-A'))).toBe('be-1');
    expect(lastSocketUrl()).toBe('ws://mock/ws/terminal/attach/be-1?ticket=be-1.tkt');
  });

  it('reuses a stored session id on reload (mints a ticket, no new create)', async () => {
    localStorage.setItem(LS('term-B'), 'be-existing');
    vi.mocked(api.mintTerminalTicket).mockResolvedValue({ id: 'be-existing', ticket: 'be-existing.tkt2' });

    createTerminalSession('term-B', 'local');

    await vi.waitFor(() => expect(createdSockets.length).toBe(1));
    expect(api.mintTerminalTicket).toHaveBeenCalledWith('be-existing');
    expect(api.createTerminal).not.toHaveBeenCalled();
    expect(lastSocketUrl()).toContain('/ws/terminal/attach/be-existing?ticket=be-existing.tkt2');
    expect(localStorage.getItem(LS('term-B'))).toBe('be-existing');
  });

  it('falls back to creating when the stored id is stale', async () => {
    localStorage.setItem(LS('term-C'), 'dead');
    vi.mocked(api.mintTerminalTicket).mockRejectedValueOnce(new Error('culled'));
    vi.mocked(api.createTerminal).mockResolvedValue({
      id: 'be-new', type: 'local', label: 'local', created: 2, ticket: 'be-new.tkt',
    } as any);

    createTerminalSession('term-C', 'local');

    await vi.waitFor(() => expect(api.createTerminal).toHaveBeenCalledTimes(1));
    expect(api.mintTerminalTicket).toHaveBeenCalledWith('dead');     // tried the stale id first
    expect(localStorage.getItem(LS('term-C'))).toBe('be-new');       // remapped to the new one
  });

  it('default local terminal creates its own backend session instead of adopting another local session', async () => {
    vi.mocked(api.listTerminals).mockResolvedValue([
      { id: 'old', type: 'local', label: 'local', created: 1 },
      { id: 'newest', type: 'local', label: 'local', created: 5 },
      { id: 'a-ssh', type: 'ssh', label: 'n1', created: 9 },
    ] as any);
    vi.mocked(api.createTerminal).mockResolvedValue({
      id: 'be-default', type: 'local', label: 'local', created: 6, ticket: 'be-default.tkt',
    } as any);

    createTerminalSession('local-terminal', 'local');

    await vi.waitFor(() => expect(createdSockets.length).toBe(1));
    expect(api.listTerminals).not.toHaveBeenCalled();
    expect(api.createTerminal).toHaveBeenCalledTimes(1);
    expect(api.mintTerminalTicket).not.toHaveBeenCalled();
    expect(localStorage.getItem(LS('local-terminal'))).toBe('be-default');
    expect(lastSocketUrl()).toContain('/ws/terminal/attach/be-default?ticket=be-default.tkt');
  });

  it('does not attach two local tabs to the same stored backend session id', async () => {
    localStorage.setItem(LS('local-terminal'), 'shared-backend');
    localStorage.setItem(LS('local-term-2'), 'shared-backend');
    vi.mocked(api.mintTerminalTicket).mockResolvedValue({ id: 'shared-backend', ticket: 'shared.tkt' });
    vi.mocked(api.createTerminal).mockResolvedValue({
      id: 'be-new-local', type: 'local', label: 'local', created: 7, ticket: 'be-new-local.tkt',
    } as any);

    createTerminalSession('local-terminal', 'local');
    createTerminalSession('local-term-2', 'local');

    await vi.waitFor(() => expect(createdSockets.length).toBe(2));
    expect(api.mintTerminalTicket).toHaveBeenCalledTimes(1);
    expect(api.mintTerminalTicket).toHaveBeenCalledWith('shared-backend');
    expect(api.createTerminal).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(LS('local-terminal'))).toBe('shared-backend');
    expect(localStorage.getItem(LS('local-term-2'))).toBe('be-new-local');
    expect(createdSockets.map(s => s.url).sort()).toEqual([
      'ws://mock/ws/terminal/attach/be-new-local?ticket=be-new-local.tkt',
      'ws://mock/ws/terminal/attach/shared-backend?ticket=shared.tkt',
    ]);
  });
});

describe('destroying a session', () => {
  it('kills the backend session and clears its stored mapping', async () => {
    vi.mocked(api.createTerminal).mockResolvedValue({
      id: 'be-9', type: 'local', label: 'local', created: 1, ticket: 'be-9.tkt',
    } as any);

    createTerminalSession('term-D', 'local');
    await vi.waitFor(() => expect(localStorage.getItem(LS('term-D'))).toBe('be-9'));

    destroyTerminalSession('term-D');

    expect(api.deleteTerminal).toHaveBeenCalledWith('be-9');   // ≠ reload: explicit close kills it
    expect(localStorage.getItem(LS('term-D'))).toBeNull();
    expect(hasTerminalSession('term-D')).toBe(false);
  });
});
