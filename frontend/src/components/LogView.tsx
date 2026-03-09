'use client';
import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { buildWsUrl } from '../utils/wsUrl';

const TERM_THEME = {
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

export default function LogView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      cursorBlink: false,
      disableStdin: true,
      fontSize: 12,
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      theme: { ...TERM_THEME },
      convertEol: true,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(containerRef.current);
    fitAddon.fit();
    termRef.current = term;

    term.writeln('\x1b[36m[log] Connecting to log stream...\x1b[0m');

    const wsUrl = buildWsUrl('/ws/logs');
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      term.write(event.data);
    };

    ws.onerror = () => {
      term.writeln('\x1b[31m[log] WebSocket error.\x1b[0m');
    };

    ws.onclose = () => {
      term.writeln('\x1b[33m[log] Connection closed.\x1b[0m');
    };

    const resizeObserver = new ResizeObserver(() => {
      fitAddon.fit();
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      ws.close();
      term.dispose();
      termRef.current = null;
    };
  }, []);

  return <div className="bp-terminal-container" ref={containerRef} />;
}
