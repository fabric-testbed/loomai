'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { buildWsUrl } from '../utils/wsUrl';
import { getAiModels, getClaudeConfigFiles, updateClaudeConfigFile, triggerClaudeBackup, resetToolConfig, browseAiFolders, type ClaudeConfigFile, type FolderBrowseResult } from '../api/client';
import '../styles/terminal-companion.css';

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

interface ToolMeta {
  name: string;
  icon: string;
  iconClass: string;
  tagline: string;
  desc: string;
  tips: string;
  badge: string;
  badgeClass: string;
}

const TOOL_INFO: Record<string, ToolMeta> = {
  claude: {
    name: 'Claude Code',
    icon: 'CC',
    iconClass: 'claude',
    tagline: "Anthropic's agentic coding CLI",
    desc: "The most powerful AI coding assistant available. Requires your own paid Anthropic subscription (Max or API). Charges apply to your account.",
    tips: 'Type /help for available commands. Use Ctrl+C to cancel. Type /exit to quit.',
    badge: 'Paid Subscription',
    badgeClass: 'paid',
  },
  aider: {
    name: 'Aider',
    icon: 'Ai',
    iconClass: 'aider',
    tagline: 'AI pair programming in your terminal',
    desc: 'Edit files, generate scripts, and refactor code. Powered by FABRIC-hosted LLMs — free with a FABRIC API key.',
    tips: 'Use /add to add files to the chat. /help for all commands.',
    badge: 'Free \u2022 API Key Required',
    badgeClass: 'free',
  },
  opencode: {
    name: 'OpenCode',
    icon: 'OC',
    iconClass: 'opencode',
    tagline: 'Terminal-based AI coding assistant',
    desc: 'Interactive AI assistant with FABRIC tools. Powered by FABRIC-hosted LLMs — free with a FABRIC API key.',
    tips: 'Type your request at the prompt. Use Ctrl+C to cancel.',
    badge: 'Free \u2022 API Key Required',
    badgeClass: 'free',
  },
};

function SidebarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <line x1="9" y1="3" x2="9" y2="21" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10" />
      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
    </svg>
  );
}

function FolderIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function ChevronUpIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="18 15 12 9 6 15" />
    </svg>
  );
}

interface Props {
  toolId: string;
  visible?: boolean;
}

export default function TerminalCompanionView({ toolId, visible = true }: Props) {
  const info = TOOL_INFO[toolId] ?? { name: toolId, icon: '?', iconClass: '', desc: '', tips: '' };
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [connected, setConnected] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const fitRef = useRef<FitAddon | null>(null);

  // Model picker state (OpenCode, Crush, Deep Agents)
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [nrpModels, setNrpModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [modelsLoading, setModelsLoading] = useState(false);
  const selectedModelRef = useRef('');
  const hasModelPicker = toolId === 'opencode' || toolId === 'crush' || toolId === 'deepagents';

  // Claude Code config state
  const [configFiles, setConfigFiles] = useState<ClaudeConfigFile[]>([]);
  const [loggedIn, setLoggedIn] = useState(false);
  const [accountEmail, setAccountEmail] = useState<string | null>(null);
  const [editingFile, setEditingFile] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [configMsg, setConfigMsg] = useState('');
  const [showConfig, setShowConfig] = useState(false);

  // Folder picker state (Claude Code)
  const [showFolderPicker, setShowFolderPicker] = useState(false);
  const [selectedFolder, setSelectedFolder] = useState('');
  const selectedFolderRef = useRef('');
  const [browseResult, setBrowseResult] = useState<FolderBrowseResult | null>(null);
  const [browsing, setBrowsing] = useState(false);

  const loadClaudeConfig = useCallback(() => {
    if (toolId !== 'claude') return;
    getClaudeConfigFiles().then((data) => {
      setConfigFiles(data.files);
      setLoggedIn(data.logged_in);
      setAccountEmail(data.account_email);
    }).catch(() => {});
  }, [toolId]);

  const browseTo = useCallback((path?: string) => {
    setBrowsing(true);
    browseAiFolders(path).then((result) => {
      setBrowseResult(result);
    }).catch(() => {}).finally(() => setBrowsing(false));
  }, []);

  useEffect(() => {
    if (hasModelPicker) {
      setModelsLoading(true);
      getAiModels().then((data) => {
        setAvailableModels(data.models || []);
        setNrpModels(data.nrp_models || []);
        const def = data.default || (data.models?.[0] ?? '');
        setSelectedModel(def);
        selectedModelRef.current = def;
      }).catch(() => {}).finally(() => setModelsLoading(false));
    }
    if (toolId === 'claude') {
      loadClaudeConfig();
    }
  }, [toolId, loadClaudeConfig]);

  const restartSession = useCallback(() => {
    // Close existing connection and terminal
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (termRef.current) {
      termRef.current.dispose();
      termRef.current = null;
    }
    // Re-create
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

    term.writeln(`\x1b[36m[${info.name}] Connecting...\x1b[0m`);

    const params = new URLSearchParams();
    if (hasModelPicker && selectedModelRef.current) {
      params.set('model', selectedModelRef.current);
    }
    if (toolId === 'claude' && selectedFolderRef.current) {
      params.set('cwd', selectedFolderRef.current);
    }
    const qs = params.toString() ? `?${params.toString()}` : '';
    const wsUrl = buildWsUrl(`/ws/terminal/ai/${encodeURIComponent(toolId)}${qs}`);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
    };

    ws.onmessage = (event) => {
      term.write(event.data);
    };

    ws.onerror = () => {
      setConnected(false);
      term.writeln('\r\n\x1b[31mWebSocket error.\x1b[0m');
    };

    ws.onclose = () => {
      setConnected(false);
      term.writeln('\r\n\x1b[33mConnection closed.\x1b[0m');
    };

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'input', data }));
      }
    });
  }, [toolId, info.name]);

  useEffect(() => {
    restartSession();

    const container = containerRef.current;
    let resizeObserver: ResizeObserver | null = null;
    if (container) {
      resizeObserver = new ResizeObserver(() => {
        fitRef.current?.fit();
        if (wsRef.current?.readyState === WebSocket.OPEN && termRef.current) {
          wsRef.current.send(JSON.stringify({ type: 'resize', cols: termRef.current.cols, rows: termRef.current.rows }));
        }
      });
      resizeObserver.observe(container);
    }

    return () => {
      resizeObserver?.disconnect();
      wsRef.current?.close();
      termRef.current?.dispose();
      wsRef.current = null;
      termRef.current = null;
      fitRef.current = null;
    };
  }, [toolId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Force full terminal repaint: fit canvas, toggle resize to force redraw, send SIGWINCH
  const refreshTerminal = useCallback(() => {
    const t = termRef.current;
    const fit = fitRef.current;
    if (!t || !fit) return;
    fit.fit();
    const { cols, rows } = t;
    if (cols > 1) {
      t.resize(cols - 1, rows);
      t.resize(cols, rows);
    }
    t.refresh(0, t.rows - 1);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'resize', cols: t.cols, rows: t.rows }));
    }
  }, []);

  // Auto-refresh when view becomes visible again
  const prevVisible = useRef(visible);
  useEffect(() => {
    const wasHidden = !prevVisible.current;
    prevVisible.current = visible;
    if (!visible || !wasHidden) return;
    const timer = setTimeout(refreshTerminal, 100);
    return () => clearTimeout(timer);
  }, [visible, refreshTerminal]);

  return (
    <div className="tc-layout">
      <div className={`tc-sidebar ${sidebarOpen ? '' : 'collapsed'}`}>
        <div className="tc-sidebar-header">
          <span className={`tc-sidebar-icon ${info.iconClass}`}>{info.icon}</span>
          <span className="tc-sidebar-title">{info.name}</span>
          <button className="tc-sidebar-toggle" onClick={() => setSidebarOpen(false)} title="Hide sidebar">
            <SidebarIcon />
          </button>
        </div>
        <div className="tc-sidebar-section">
          <div className="tc-sidebar-branding">
            <div className="tc-sidebar-tagline">{info.tagline}</div>
            <span className={`tc-sidebar-badge ${info.badgeClass}`}>{info.badge}</span>
          </div>
          <div className="tc-sidebar-desc">{info.desc}</div>
          {toolId === 'claude' && (
            <div className="tc-folder-picker">
              <button
                className="tc-folder-picker-toggle"
                onClick={() => {
                  const opening = !showFolderPicker;
                  setShowFolderPicker(opening);
                  if (opening) browseTo(selectedFolder || undefined);
                }}
              >
                <FolderIcon />
                <span className="tc-folder-picker-label">
                  {selectedFolder ? selectedFolder.split('/').pop() || selectedFolder : 'Default workspace'}
                </span>
              </button>
              {showFolderPicker && browseResult && (
                <div className="tc-folder-browser">
                  <div className="tc-folder-browser-path">
                    {browseResult.parent !== null && (
                      <button
                        className="tc-folder-nav-btn"
                        onClick={() => browseTo(browseResult.parent!)}
                        title="Go up"
                        disabled={browsing}
                      >
                        <ChevronUpIcon />
                      </button>
                    )}
                    <span className="tc-folder-current-path" title={browseResult.path}>
                      {browseResult.path}
                    </span>
                  </div>
                  <div className="tc-folder-list">
                    {browsing ? (
                      <div className="tc-folder-loading">Loading...</div>
                    ) : browseResult.folders.length === 0 ? (
                      <div className="tc-folder-empty">No subfolders</div>
                    ) : (
                      browseResult.folders.map((folder) => (
                        <button
                          key={folder}
                          className="tc-folder-item"
                          onClick={() => browseTo(`${browseResult.path}/${folder}`)}
                        >
                          <FolderIcon />
                          {folder}
                        </button>
                      ))
                    )}
                  </div>
                  <div className="tc-folder-actions">
                    <button
                      className="tc-config-btn save"
                      onClick={() => {
                        setSelectedFolder(browseResult.path);
                        selectedFolderRef.current = browseResult.path;
                        setShowFolderPicker(false);
                      }}
                    >
                      Select This Folder
                    </button>
                    {selectedFolder && (
                      <button
                        className="tc-config-btn"
                        onClick={() => {
                          setSelectedFolder('');
                          selectedFolderRef.current = '';
                          setShowFolderPicker(false);
                        }}
                      >
                        Reset
                      </button>
                    )}
                  </div>
                </div>
              )}
              {selectedFolder && (
                <div className="tc-folder-hint">
                  Session will start in: <strong>{selectedFolder}</strong>
                </div>
              )}
            </div>
          )}
          <button className="tc-new-session-btn" onClick={restartSession} title="Restart terminal session">
            <PlusIcon />
            New Session
          </button>
          <div className="tc-sidebar-status">
            <span className={`tc-status-dot ${connected ? 'connected' : 'disconnected'}`} />
            {connected ? 'Connected' : 'Disconnected'}
          </div>
          {hasModelPicker && (
            <div className="tc-model-picker">
              <label className="tc-model-label">Model</label>
              {modelsLoading ? (
                <span className="tc-model-loading">Loading models...</span>
              ) : availableModels.length > 0 ? (
                <>
                  <select
                    className="tc-model-select"
                    value={selectedModel}
                    onChange={(e) => {
                      setSelectedModel(e.target.value);
                      selectedModelRef.current = e.target.value;
                    }}
                  >
                    <optgroup label="FABRIC AI">
                      {availableModels.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </optgroup>
                    {nrpModels.length > 0 && (
                      <optgroup label="NRP">
                        {nrpModels.map((m) => (
                          <option key={`nrp:${m}`} value={m}>{m}</option>
                        ))}
                      </optgroup>
                    )}
                  </select>
                  <div className="tc-model-hint">Change model and click &ldquo;New Session&rdquo; to apply</div>
                </>
              ) : (
                <span className="tc-model-loading">No models available</span>
              )}
            </div>
          )}
          {info.tips && (
            <div className="tc-sidebar-tips">
              <strong>Tips</strong><br />
              {info.tips}
            </div>
          )}
          {toolId === 'claude' && (
            <div className="tc-claude-config">
              <button
                className="tc-config-toggle"
                onClick={() => { setShowConfig(!showConfig); if (!showConfig) loadClaudeConfig(); }}
              >
                {showConfig ? '▾' : '▸'} Settings
              </button>
              {showConfig && (
                <div className="tc-config-panel">
                  <div className="tc-config-status">
                    <span className={`tc-status-dot ${loggedIn ? 'connected' : 'disconnected'}`} />
                    {loggedIn ? (accountEmail || 'Logged in') : 'Not logged in'}
                  </div>
                  <div className="tc-config-actions">
                    <button className="tc-config-btn" onClick={() => {
                      triggerClaudeBackup().then(() => {
                        setConfigMsg('Config backed up');
                        loadClaudeConfig();
                        setTimeout(() => setConfigMsg(''), 3000);
                      }).catch(() => setConfigMsg('Backup failed'));
                    }}>Save Current Config</button>
                    <button className="tc-config-btn danger" onClick={() => {
                      if (confirm('Reset Claude Code config to defaults? You will need to log in again.')) {
                        resetToolConfig('claude-code').then(() => {
                          setConfigMsg('Reset to defaults');
                          loadClaudeConfig();
                          setTimeout(() => setConfigMsg(''), 3000);
                        }).catch(() => setConfigMsg('Reset failed'));
                      }
                    }}>Reset to Defaults</button>
                  </div>
                  {configMsg && <div className="tc-config-msg">{configMsg}</div>}
                  <div className="tc-config-files">
                    <div className="tc-config-files-label">Config Files <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>(persisted across rebuilds)</span></div>
                    {configFiles.map((cf) => (
                      <div key={cf.name} className="tc-config-file-row">
                        <span className={`tc-config-file-name ${cf.content === null ? 'missing' : ''}`}>
                          {cf.name}
                        </span>
                        {cf.content !== null ? (
                          <button className="tc-config-file-btn" onClick={() => {
                            if (editingFile === cf.name) {
                              setEditingFile(null);
                            } else {
                              setEditingFile(cf.name);
                              setEditContent(cf.content || '');
                            }
                          }}>{editingFile === cf.name ? 'Close' : 'Edit'}</button>
                        ) : (
                          <button className="tc-config-file-btn" onClick={() => {
                            setEditingFile(cf.name);
                            setEditContent(cf.name.endsWith('.json') ? '{}' : '');
                          }}>Create</button>
                        )}
                      </div>
                    ))}
                  </div>
                  {editingFile && (
                    <div className="tc-config-editor">
                      <div className="tc-config-editor-header">
                        <span>{editingFile}</span>
                        <button className="tc-config-btn save" onClick={() => {
                          updateClaudeConfigFile(editingFile, editContent).then(() => {
                            setConfigMsg(`Saved ${editingFile}`);
                            setEditingFile(null);
                            loadClaudeConfig();
                            setTimeout(() => setConfigMsg(''), 3000);
                          }).catch((err) => setConfigMsg(`Save failed: ${err.message}`));
                        }}>Save</button>
                      </div>
                      <textarea
                        className="tc-config-textarea"
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                        spellCheck={false}
                      />
                    </div>
                  )}
                  <div className="tc-config-hint">
                    Changes take effect on next session. Click &ldquo;New Session&rdquo; to apply.
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      <div className="tc-main">
        <div className="tc-main-header">
          {!sidebarOpen && (
            <button className="tc-sidebar-open-btn" onClick={() => setSidebarOpen(true)} title="Show sidebar">
              <SidebarIcon />
            </button>
          )}
          <span className="tc-header-title">{info.name}</span>
          <span className="tc-header-badge">Terminal</span>
          <button className="tc-popout-btn" onClick={() => window.open(`/popout?tool=${encodeURIComponent(toolId)}`, '_blank')} title="Open in new tab">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
          </button>
          <button className="tc-refresh-btn" onClick={refreshTerminal} title="Refresh terminal display">
            <RefreshIcon />
          </button>
        </div>
        <div className="tc-terminal-wrapper">
          <div className="tc-terminal-inner" ref={containerRef} />
        </div>
      </div>
    </div>
  );
}
