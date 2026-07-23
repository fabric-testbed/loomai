import type { Terminal } from '@xterm/xterm';

/**
 * Wire browser clipboard copy/paste into an xterm terminal.
 *
 * xterm renders to a canvas, so OS clipboard shortcuts don't reach it on their
 * own — without this, users can't copy a long OAuth URL out or paste a token
 * back (e.g. the in-container Claude Code / Codex logins).
 *
 * - Copy: Cmd+C (macOS) or Ctrl+Shift+C — only when text is selected, so plain
 *   Ctrl+C still passes through as SIGINT.
 * - Paste: Cmd+V (macOS) or Ctrl+Shift+V — reads the clipboard and feeds it to
 *   the PTY via term.paste() (honors bracketed-paste mode).
 *
 * Requires a secure context (https/localhost) for the async Clipboard API.
 * Shared by every terminal surface: the BottomPanel terminals (terminalStore),
 * the AI companion terminal, and the tool-config companion terminal.
 */
export function wireClipboard(term: Terminal): void {
  term.attachCustomKeyEventHandler((e: KeyboardEvent): boolean => {
    if (e.type !== 'keydown') return true;
    const key = e.key.toLowerCase();
    const isCopy = (e.metaKey && !e.ctrlKey && key === 'c') || (e.ctrlKey && e.shiftKey && key === 'c');
    const isPaste = (e.metaKey && !e.ctrlKey && key === 'v') || (e.ctrlKey && e.shiftKey && key === 'v');

    if (isCopy) {
      const sel = term.getSelection();
      if (!sel) return true; // nothing selected — let the key through (e.g. SIGINT paths)
      e.preventDefault();
      navigator.clipboard?.writeText(sel).catch(() => {});
      return false;
    }
    if (isPaste) {
      e.preventDefault();
      navigator.clipboard?.readText().then((text) => {
        if (text) term.paste(text);
      }).catch(() => {});
      return false;
    }
    return true;
  });
}
