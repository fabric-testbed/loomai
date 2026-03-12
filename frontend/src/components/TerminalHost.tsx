/**
 * TerminalHost — renders a persistent terminal session.
 *
 * On mount, attaches the terminal's DOM element to this host div.
 * On unmount, detaches the DOM element but keeps the session alive.
 * The session is only destroyed when explicitly closed via destroyTerminalSession().
 *
 * Uses IntersectionObserver to detect when the terminal becomes visible
 * (e.g. tab switch, view change) and refreshes the xterm.js canvas.
 */
import React, { useRef, useEffect } from 'react';
import { createTerminalSession } from '../utils/terminalStore';
import type { TerminalSession } from '../utils/terminalStore';

interface TerminalHostProps {
  sessionId: string;
  type: 'ssh' | 'local';
  sliceName?: string;
  nodeName?: string;
  managementIp?: string;
}

function refitSession(session: TerminalSession) {
  try {
    session.fitAddon.fit();
    session.term.refresh(0, session.term.rows - 1);
    if (session.ws.readyState === WebSocket.OPEN) {
      session.ws.send(
        JSON.stringify({ type: 'resize', cols: session.term.cols, rows: session.term.rows }),
      );
    }
  } catch {
    /* ignore */
  }
}

export default React.memo(function TerminalHost({
  sessionId,
  type,
  sliceName,
  nodeName,
  managementIp,
}: TerminalHostProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef<TerminalSession | null>(null);

  useEffect(() => {
    if (!hostRef.current) return;

    const sshInfo =
      type === 'ssh' && sliceName && nodeName && managementIp
        ? { sliceName, nodeName, managementIp }
        : undefined;

    const session = createTerminalSession(sessionId, type, sshInfo);
    sessionRef.current = session;
    const host = hostRef.current;

    // Attach terminal's persistent DOM element into this host
    host.appendChild(session.containerEl);

    // Refit after a frame so dimensions are correct
    requestAnimationFrame(() => refitSession(session));

    // Watch for visibility changes (tab switches, view changes)
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && sessionRef.current) {
          requestAnimationFrame(() => refitSession(sessionRef.current!));
        }
      },
      { threshold: 0.1 },
    );
    observer.observe(host);

    return () => {
      observer.disconnect();
      // Detach only — session persists for reattachment elsewhere
      if (session.containerEl.parentNode === host) {
        host.removeChild(session.containerEl);
      }
    };
  }, [sessionId, type, sliceName, nodeName, managementIp]);

  return <div ref={hostRef} style={{ width: '100%', height: '100%' }} />;
});
