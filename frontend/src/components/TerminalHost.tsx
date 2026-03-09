/**
 * TerminalHost — renders a persistent terminal session.
 *
 * On mount, attaches the terminal's DOM element to this host div.
 * On unmount, detaches the DOM element but keeps the session alive.
 * The session is only destroyed when explicitly closed via destroyTerminalSession().
 */
import React, { useRef, useEffect } from 'react';
import { createTerminalSession } from '../utils/terminalStore';

interface TerminalHostProps {
  sessionId: string;
  type: 'ssh' | 'local';
  sliceName?: string;
  nodeName?: string;
  managementIp?: string;
}

export default function TerminalHost({
  sessionId,
  type,
  sliceName,
  nodeName,
  managementIp,
}: TerminalHostProps) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!hostRef.current) return;

    const sshInfo =
      type === 'ssh' && sliceName && nodeName && managementIp
        ? { sliceName, nodeName, managementIp }
        : undefined;

    const session = createTerminalSession(sessionId, type, sshInfo);
    const host = hostRef.current;

    // Attach terminal's persistent DOM element into this host
    host.appendChild(session.containerEl);

    // Refit after a frame so dimensions are correct
    requestAnimationFrame(() => {
      try {
        session.fitAddon.fit();
        if (session.ws.readyState === WebSocket.OPEN) {
          session.ws.send(
            JSON.stringify({ type: 'resize', cols: session.term.cols, rows: session.term.rows }),
          );
        }
      } catch {
        /* ignore */
      }
    });

    return () => {
      // Detach only — session persists for reattachment elsewhere
      if (session.containerEl.parentNode === host) {
        host.removeChild(session.containerEl);
      }
    };
  }, [sessionId, type, sliceName, nodeName, managementIp]);

  return <div ref={hostRef} style={{ width: '100%', height: '100%' }} />;
}
