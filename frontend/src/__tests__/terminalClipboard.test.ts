import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  installTerminalClipboard,
  parseOsc52ClipboardText,
  writeClipboardText,
} from '../utils/terminalClipboard';

class FakeTerminal {
  oscHandler: ((data: string) => boolean | Promise<boolean>) | null = null;
  keyHandler: ((event: KeyboardEvent) => boolean) | null = null;
  selection = '';
  parser = {
    registerOscHandler: vi.fn((ident: number, callback: (data: string) => boolean | Promise<boolean>) => {
      this.oscHandler = callback;
      return { dispose: vi.fn() };
    }),
  };
  attachCustomKeyEventHandler = vi.fn((handler: (event: KeyboardEvent) => boolean) => {
    this.keyHandler = handler;
  });
  hasSelection = vi.fn(() => this.selection.length > 0);
  getSelection = vi.fn(() => this.selection);
}

function setClipboardMock(writeText = vi.fn().mockResolvedValue(undefined)) {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText },
  });
  return writeText;
}

function keyEvent(overrides: Partial<KeyboardEvent> = {}) {
  return {
    type: 'keydown',
    key: 'c',
    metaKey: true,
    ctrlKey: false,
    shiftKey: false,
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
    ...overrides,
  } as unknown as KeyboardEvent;
}

describe('terminal clipboard helpers', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setClipboardMock();
  });

  it('parses OSC 52 clipboard text as UTF-8', () => {
    const payload = btoa(String.fromCharCode(...new TextEncoder().encode('hello \u2713')));

    expect(parseOsc52ClipboardText(`c;${payload}`)).toBe('hello \u2713');
  });

  it('rejects OSC 52 clipboard queries and malformed payloads', () => {
    expect(parseOsc52ClipboardText('c;?')).toBeNull();
    expect(parseOsc52ClipboardText('c;not valid base64')).toBeNull();
    expect(parseOsc52ClipboardText('bad-target;abcd')).toBeNull();
  });

  it('copies OSC 52 payloads to the browser clipboard', async () => {
    const writeText = setClipboardMock();
    const term = new FakeTerminal();
    installTerminalClipboard(term as any);
    const payload = btoa('copied from claude');

    await term.oscHandler?.(`c;${payload}`);

    expect(term.parser.registerOscHandler).toHaveBeenCalledWith(52, expect.any(Function));
    expect(writeText).toHaveBeenCalledWith('copied from claude');
  });

  it('copies xterm selection on Cmd+C without sending c to the PTY', async () => {
    const writeText = setClipboardMock();
    const term = new FakeTerminal();
    term.selection = 'selected output';
    installTerminalClipboard(term as any);
    const event = keyEvent();

    const handled = term.keyHandler?.(event);

    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith('selected output'));
    expect(handled).toBe(false);
    expect(event.preventDefault).toHaveBeenCalled();
    expect(event.stopPropagation).toHaveBeenCalled();
  });

  it('does not intercept Cmd+C when there is no terminal selection', () => {
    const writeText = setClipboardMock();
    const term = new FakeTerminal();
    installTerminalClipboard(term as any);
    const event = keyEvent();

    const handled = term.keyHandler?.(event);

    expect(handled).toBe(true);
    expect(writeText).not.toHaveBeenCalled();
  });

  it('falls back to textarea copy when async clipboard writes fail', async () => {
    setClipboardMock(vi.fn().mockRejectedValue(new Error('denied')));
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommand,
    });

    await expect(writeClipboardText('fallback text')).resolves.toBe(true);

    expect(execCommand).toHaveBeenCalledWith('copy');
  });
});
