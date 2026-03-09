'use client';
import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import '../styles/terminal.css';
import { buildWsUrl } from '../utils/wsUrl';

interface TerminalPanelProps {
  sliceName: string;
  nodeName: string;
  managementIp: string;
  onClose: () => void;
}

export default function TerminalPanel({ sliceName, nodeName, managementIp, onClose }: TerminalPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, monospace",
      theme: {
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
      },
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(containerRef.current);
    fitAddon.fit();
    termRef.current = term;

    term.writeln(`\x1b[36m[terminal] Opening session to ${nodeName} (${managementIp})...\x1b[0m`);

    // Connect WebSocket
    const wsUrl = buildWsUrl(`/ws/terminal/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}`);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      // Send initial resize — progress messages come from the backend
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

    // Send terminal input to WebSocket
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'input', data }));
      }
    });

    // Handle resize
    const resizeObserver = new ResizeObserver(() => {
      fitAddon.fit();
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      ws.close();
      term.dispose();
      termRef.current = null;
      wsRef.current = null;
    };
  }, [sliceName, nodeName, managementIp]);

  return (
    <div className="terminal-panel">
      <div className="terminal-header">
        <span className="terminal-title">SSH: {nodeName} ({managementIp})</span>
        <button className="terminal-close" onClick={onClose} title="Close terminal">✕</button>
      </div>
      <div className="terminal-container" ref={containerRef} />
    </div>
  );
}
