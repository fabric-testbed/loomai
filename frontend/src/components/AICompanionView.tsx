'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { buildWsUrl } from '../utils/wsUrl';
import { getConfig, getAiTools, getToolInstallStatus, type ToolInstallInfo } from '../api/client';
import ContainerFileBrowser from './ContainerFileBrowser';
import TerminalCompanionView from './TerminalCompanionView';
import OpenCodeWebView from './OpenCodeWebView';
import AiderWebView from './AiderWebView';
import LoomAIChatView from './LoomAIChatView';
import '../styles/ai-companion.css';

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
  yellow: '#ffca28',
  brightYellow: '#ffd54f',
  blue: '#5798bc',
  brightBlue: '#6db3d6',
  magenta: '#ab47bc',
  brightMagenta: '#ce93d8',
  cyan: '#26c6da',
  brightCyan: '#4dd0e1',
  white: '#e0e0e0',
  brightWhite: '#ffffff',
};

interface ToolDef {
  id: string;
  name: string;
  desc: string;
  icon: string;
  iconClass: string;
  needsKey: boolean;
  warning?: string;
}

const TOOLS: ToolDef[] = [
  {
    id: 'loomai',
    name: 'LoomAI',
    desc: 'Chat-based AI assistant with FABRIC tools — create slices, query resources, and manage experiments through natural conversation.',
    icon: '\u2728',
    iconClass: 'loomai',
    needsKey: true,
  },
  {
    id: 'aider',
    name: 'Aider',
    desc: 'AI pair programming — edit files, generate scripts, and refactor code. Powered by FABRIC-hosted LLMs. Requires a free FABRIC API key.',
    icon: 'Ai',
    iconClass: 'aider',
    needsKey: true,
  },
  {
    id: 'opencode',
    name: 'OpenCode',
    desc: 'Interactive AI coding assistant with integrated FABRIC tools, skills, and agents. Powered by FABRIC-hosted LLMs. Requires a free FABRIC API key.',
    icon: 'OC',
    iconClass: 'opencode',
    needsKey: true,
  },
  {
    id: 'crush',
    name: 'Crush',
    desc: 'Terminal-based AI coding assistant from Charm. Supports FABRIC and NRP LLMs. Requires a free FABRIC API key.',
    icon: 'Cr',
    iconClass: 'crush',
    needsKey: true,
  },
  {
    id: 'deepagents',
    name: 'Deep Agents',
    desc: 'LangChain\'s open-source coding agent with planning, memory, and skills. Powered by FABRIC-hosted LLMs. Requires a free FABRIC API key.',
    icon: 'DA',
    iconClass: 'deepagents',
    needsKey: true,
  },
  {
    id: 'claude',
    name: 'Claude Code',
    desc: 'Anthropic\'s most powerful agentic coding CLI. Requires your own paid Anthropic subscription (Max or API).',
    icon: 'CC',
    iconClass: 'claude',
    needsKey: false,
    warning: 'Claude Code requires a paid Anthropic account (Max or API). Charges will apply to your account. Continue?',
  },
];

interface TabState {
  id: string;
  toolId: string;
  label: string;
}

interface AICompanionViewProps {
  selectedTool?: string | null;
  onToolChange?: (toolId: string | null) => void;
  visible?: boolean;
}

export default function AICompanionView({ selectedTool, onToolChange, visible = true }: AICompanionViewProps) {
  const [hasKey, setHasKey] = useState<boolean | null>(null);
  const [enabledTools, setEnabledTools] = useState<Record<string, boolean>>({});
  const [tabs, setTabs] = useState<TabState[]>([]);
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [showWarning, setShowWarning] = useState<ToolDef | null>(null);
  const [installStatus, setInstallStatus] = useState<Record<string, ToolInstallInfo>>({});

  // Resizable split pane
  const [splitPercent, setSplitPercent] = useState(50);
  const splitDragging = useRef(false);
  const splitContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getConfig().then((s) => setHasKey(!!s.ai_api_key_set)).catch(() => setHasKey(false));
    getAiTools().then(setEnabledTools).catch(() => {});
    getToolInstallStatus().then(setInstallStatus).catch(() => {});
  }, []);

  const visibleTools = TOOLS.filter((t) => enabledTools[t.id] !== false);

  const launchTool = useCallback((tool: ToolDef) => {
    const tabId = `${tool.id}-${Date.now()}`;
    const newTab: TabState = { id: tabId, toolId: tool.id, label: tool.name };
    setTabs((prev) => [...prev, newTab]);
    setActiveTab(tabId);
  }, []);

  const handleLaunch = useCallback((tool: ToolDef) => {
    if (tool.warning) {
      setShowWarning(tool);
    } else {
      launchTool(tool);
    }
  }, [launchTool]);

  const closeTab = useCallback((tabId: string) => {
    setTabs((prev) => {
      const next = prev.filter((t) => t.id !== tabId);
      if (activeTab === tabId) {
        setActiveTab(next.length > 0 ? next[next.length - 1].id : null);
      }
      return next;
    });
  }, [activeTab]);

  // Split divider drag handler
  const handleDividerMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    splitDragging.current = true;

    const onMouseMove = (ev: MouseEvent) => {
      if (!splitDragging.current || !splitContainerRef.current) return;
      const rect = splitContainerRef.current.getBoundingClientRect();
      const pct = ((ev.clientX - rect.left) / rect.width) * 100;
      setSplitPercent(Math.max(20, Math.min(80, pct)));
    };

    const onMouseUp = () => {
      splitDragging.current = false;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }, []);

  const showCards = tabs.length === 0 && !selectedTool;

  // When a tool is directly selected (from the View dropdown sub-menu),
  // render it full-screen without the card launcher or split pane
  const renderDirectTool = () => {
    if (!selectedTool) return null;
    if (selectedTool === 'loomai') return <LoomAIChatView visible={visible} />;
    if (selectedTool === 'opencode') return <OpenCodeWebView visible={visible} />;
    if (selectedTool === 'aider') return <AiderWebView visible={visible} />;
    return <TerminalCompanionView toolId={selectedTool} visible={visible} />;
  };

  return (
    <div className="ai-companion">
      {showWarning && (
        <div className="ai-modal-overlay" onClick={() => setShowWarning(null)}>
          <div className="ai-modal" onClick={(e) => e.stopPropagation()}>
            <h3>{'\u26A0'} {showWarning.name}</h3>
            <p>{showWarning.warning}</p>
            <div className="ai-modal-actions">
              <button className="ai-modal-cancel" onClick={() => setShowWarning(null)}>Cancel</button>
              <button className="ai-modal-confirm" onClick={() => { launchTool(showWarning); setShowWarning(null); }}>
                Launch Anyway
              </button>
            </div>
          </div>
        </div>
      )}

      {selectedTool ? (
        renderDirectTool()
      ) : showCards ? (
        <div className="ai-cards" data-help-id="ai-companion.launcher">
          {visibleTools.map((tool) => {
            const ready = tool.needsKey ? hasKey : true;
            const toolStatus = installStatus[tool.id];
            const isInstalled = !toolStatus || toolStatus.installed;
            const badge = tool.id === 'claude'
              ? { cls: 'your-account', text: 'Paid Subscription' }
              : tool.id === 'loomai'
                ? (ready ? { cls: 'free', text: 'Free \u2022 API Key Required' } : { cls: 'key-required', text: 'API Key Required' })
                : ready
                  ? { cls: 'free', text: 'Free \u2022 API Key Required' }
                  : { cls: 'key-required', text: 'API Key Required' };
            const installBadge = toolStatus && !toolStatus.installed
              ? { cls: 'not-installed', text: `Install \u2022 ${toolStatus.size_estimate}` }
              : null;

            return (
              <div className="ai-card" key={tool.id} onClick={() => onToolChange?.(tool.id)}>
                <div className="ai-card-header">
                  <div className={`ai-card-icon ${tool.iconClass}`}>{tool.icon}</div>
                  <div className="ai-card-name">{tool.name}</div>
                </div>
                <div className="ai-card-desc">{tool.desc}</div>
                <div className="ai-card-footer">
                  <span className={`ai-badge ${badge.cls}`}>{badge.text}</span>
                  {installBadge && <span className={`ai-badge ${installBadge.cls}`}>{installBadge.text}</span>}
                  <button
                    className="ai-launch-btn"
                    disabled={tool.needsKey && !ready}
                    onClick={(e) => { e.stopPropagation(); onToolChange?.(tool.id); }}
                  >
                    {installBadge ? 'Install & Launch' : 'Launch'}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="ai-split" ref={splitContainerRef}>
          <div className="ai-split-left" style={{ width: `${splitPercent}%` }}>
            <div className="ai-tabs-area">
              <div className="ai-tab-bar">
                {tabs.map((tab) => (
                  <div
                    key={tab.id}
                    className={`ai-tab ${activeTab === tab.id ? 'active' : ''}`}
                    onClick={() => setActiveTab(tab.id)}
                  >
                    {tab.label}
                    <button className="ai-tab-close" onClick={(e) => { e.stopPropagation(); closeTab(tab.id); }}>{'\u2715'}</button>
                  </div>
                ))}
                <button className="ai-tab-new" onClick={() => setTabs([])} title="Back to launcher">{'\u2b12'}</button>
              </div>
              <div className="ai-terminal-pane">
                {tabs.map((tab) => (
                  <div key={tab.id} style={{ width: '100%', height: '100%', display: activeTab === tab.id ? 'block' : 'none' }}>
                    <AITerminalPane toolId={tab.toolId} tabId={tab.id} />
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="ai-split-divider" onMouseDown={handleDividerMouseDown} />
          <div className="ai-split-right" style={{ width: `calc(${100 - splitPercent}% - 5px)` }}>
            <ContainerFileBrowser />
          </div>
        </div>
      )}
    </div>
  );
}

function AITerminalPane({ toolId, tabId }: { toolId: string; tabId: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, monospace",
      theme: { ...TERM_THEME },
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(containerRef.current);
    fitAddon.fit();
    termRef.current = term;
    fitRef.current = fitAddon;

    term.writeln(`\x1b[36m[ai] Launching ${toolId}...\x1b[0m`);

    const wsUrl = buildWsUrl(`/ws/terminal/ai/${encodeURIComponent(toolId)}`);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

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
      fitRef.current = null;
      wsRef.current = null;
    };
  }, [toolId, tabId]);

  return <div className="ai-terminal-container" ref={containerRef} />;
}
