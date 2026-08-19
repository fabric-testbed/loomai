import type { IDisposable, ITerminalOptions, Terminal } from '@xterm/xterm';

const MAX_OSC52_PAYLOAD_CHARS = 4 * 1024 * 1024;

export const TERMINAL_CLIPBOARD_OPTIONS: Partial<ITerminalOptions> = {
  macOptionClickForcesSelection: true,
};

function copyViaTextArea(text: string): boolean {
  if (typeof document === 'undefined') return false;
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', 'true');
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  textarea.style.top = '0';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  try {
    return document.execCommand?.('copy') ?? false;
  } catch {
    return false;
  } finally {
    textarea.remove();
  }
}

export async function writeClipboardText(text: string): Promise<boolean> {
  const clipboard = typeof navigator !== 'undefined' ? navigator.clipboard : undefined;
  if (clipboard?.writeText) {
    try {
      await clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to the legacy path. It still works in some browsers when
      // async Clipboard API is unavailable or denied for a terminal iframe/pane.
    }
  }
  return copyViaTextArea(text);
}

function decodeBase64Utf8(payload: string): string | null {
  if (!payload || payload === '?' || payload.length > MAX_OSC52_PAYLOAD_CHARS) {
    return null;
  }
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(payload) || payload.length % 4 === 1) {
    return null;
  }
  try {
    const binary = atob(payload);
    const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  } catch {
    return null;
  }
}

export function parseOsc52ClipboardText(data: string): string | null {
  const separator = data.indexOf(';');
  if (separator < 0) return null;
  const target = data.slice(0, separator);
  const payload = data.slice(separator + 1);

  // OSC 52 targets are clipboard selection designators. Claude Code and most
  // terminal apps use "c"; accept common xterm designators and ignore queries.
  if (target && !/^(?:[cpsq0-7]+)$/i.test(target)) return null;
  return decodeBase64Utf8(payload);
}

function isCopyShortcut(event: KeyboardEvent): boolean {
  const key = event.key.toLowerCase();
  return key === 'c' && (event.metaKey || (event.ctrlKey && event.shiftKey));
}

export function installTerminalClipboard(term: Terminal): IDisposable {
  const disposables: IDisposable[] = [];

  disposables.push(term.parser.registerOscHandler(52, (data) => {
    const text = parseOsc52ClipboardText(data);
    if (text !== null) {
      void writeClipboardText(text);
    }
    return true;
  }));

  term.attachCustomKeyEventHandler((event) => {
    if (event.type === 'keydown' && isCopyShortcut(event) && term.hasSelection()) {
      const selection = term.getSelection();
      if (selection) {
        event.preventDefault();
        event.stopPropagation();
        void writeClipboardText(selection);
        return false;
      }
    }
    return true;
  });

  return {
    dispose: () => {
      disposables.forEach(disposable => disposable.dispose());
    },
  };
}
