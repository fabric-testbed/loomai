'use client';
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import { getAiModels, getChatAgents, streamChat, stopChatStream, getConfig } from '../api/client';
import type { ChatAgent } from '../api/client';
import '../styles/ai-chat-panel.css';

const VISIBLE_TOOL_COUNT = 3;

interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
  result?: string;
  expanded?: boolean;
}

interface ChatMessage {
  role: 'user' | 'assistant' | 'tool-activity';
  content: string;
  toolCalls?: ToolCall[];
}

// ---------------------------------------------------------------------------
// Module-level persistent chat store — survives component unmount/remount
// ---------------------------------------------------------------------------

interface ChatStore {
  messages: ChatMessage[];
  selectedModel: string;
  selectedAgent: string;
  streaming: boolean;
  error: string;
  abortController: AbortController | null;
  requestId: string;
  didMutate: boolean;
  /** Mounted component registers a listener to receive updates */
  listener: (() => void) | null;
  /** Queued onSliceChanged callback from component props */
  pendingSliceRefresh: boolean;
}

const _stores = new Map<string, ChatStore>();

function getStore(id: string): ChatStore {
  let s = _stores.get(id);
  if (!s) {
    s = {
      messages: [], selectedModel: '', selectedAgent: '',
      streaming: false, error: '', abortController: null,
      requestId: '', didMutate: false, listener: null,
      pendingSliceRefresh: false,
    };
    _stores.set(id, s);
  }
  return s;
}

const MUTATING_TOOLS = new Set([
  'create_slice', 'add_node', 'add_component', 'add_network',
  'submit_slice', 'delete_slice', 'renew_slice', 'load_template',
  'save_as_template', 'remove_node', 'remove_network',
]);

/** Run a chat stream at the module level — continues even if component unmounts */
async function runModuleStream(
  storeId: string,
  apiMessages: Array<{ role: string; content: string }>,
  model: string,
  agent: string,
  sliceContext: string | undefined,
) {
  const store = getStore(storeId);
  const reqId = `chat-${Date.now()}`;
  const controller = new AbortController();

  store.streaming = true;
  store.error = '';
  store.abortController = controller;
  store.requestId = reqId;
  store.didMutate = false;
  store.pendingSliceRefresh = false;

  // Add empty assistant message to stream into
  store.messages = [...store.messages, { role: 'assistant' as const, content: '', toolCalls: [] }];
  store.listener?.();

  let currentToolCalls: ToolCall[] = [];

  try {
    for await (const chunk of streamChat(apiMessages, model, {
      agent: agent || undefined,
      sliceContext,
      requestId: reqId,
      signal: controller.signal,
    })) {
      if (chunk.error) {
        store.error = chunk.error;
        const last = store.messages[store.messages.length - 1];
        if (last?.role === 'assistant' && !last.content && (!last.toolCalls || last.toolCalls.length === 0)) {
          store.messages = store.messages.slice(0, -1);
        }
        store.listener?.();
        break;
      }

      // Tool call notification
      if ((chunk as any).tool_call) {
        const tc = (chunk as any).tool_call;
        currentToolCalls = [...currentToolCalls, { name: tc.name, arguments: tc.arguments }];
        if (MUTATING_TOOLS.has(tc.name)) store.didMutate = true;
        const msgs = [...store.messages];
        const last = msgs[msgs.length - 1];
        if (last?.role === 'assistant') {
          msgs[msgs.length - 1] = { ...last, toolCalls: [...currentToolCalls] };
        }
        store.messages = msgs;
        store.listener?.();
        continue;
      }

      // Tool result notification
      if ((chunk as any).tool_result) {
        const tr = (chunk as any).tool_result;
        currentToolCalls = currentToolCalls.map(tc =>
          tc.name === tr.name && !tc.result ? { ...tc, result: tr.result } : tc
        );
        const msgs = [...store.messages];
        const last = msgs[msgs.length - 1];
        if (last?.role === 'assistant') {
          msgs[msgs.length - 1] = { ...last, toolCalls: [...currentToolCalls] };
        }
        store.messages = msgs;
        store.listener?.();
        continue;
      }

      // Regular content
      if (chunk.content) {
        const msgs = [...store.messages];
        const last = msgs[msgs.length - 1];
        if (last?.role === 'assistant') {
          msgs[msgs.length - 1] = { ...last, content: last.content + chunk.content };
        }
        store.messages = msgs;
        store.listener?.();
      }

      if (chunk.done) break;
    }
  } catch (e: any) {
    if (e.name !== 'AbortError') {
      store.error = e.message || 'Stream failed';
      const last = store.messages[store.messages.length - 1];
      if (last?.role === 'assistant' && !last.content && (!last.toolCalls || last.toolCalls.length === 0)) {
        store.messages = store.messages.slice(0, -1);
      }
      store.listener?.();
    }
  } finally {
    store.streaming = false;
    store.abortController = null;
    store.requestId = '';
    if (store.didMutate) store.pendingSliceRefresh = true;
    store.listener?.();
  }
}

function stopModuleStream(storeId: string) {
  const store = getStore(storeId);
  if (store.abortController) store.abortController.abort();
  if (store.requestId) stopChatStream(store.requestId).catch(() => {});
  store.streaming = false;
  store.abortController = null;
  store.requestId = '';
  store.listener?.();
}

function clearModuleChat(storeId: string) {
  const store = getStore(storeId);
  if (store.streaming) stopModuleStream(storeId);
  store.messages = [];
  store.error = '';
  store.listener?.();
}

// ---------------------------------------------------------------------------
// ToolCallsView — collapsible tool call list
// ---------------------------------------------------------------------------

function ToolCallsView({ toolCalls, msgIdx, onToggle, isStreaming }: {
  toolCalls: ToolCall[];
  msgIdx: number;
  onToggle: (msgIdx: number, toolIdx: number) => void;
  isStreaming: boolean;
}) {
  const [showAll, setShowAll] = useState(false);
  const total = toolCalls.length;
  const hiddenCount = total - VISIBLE_TOOL_COUNT;

  // During streaming or when few tools, decide what to show
  const visibleTools = useMemo(() => {
    if (showAll || total <= VISIBLE_TOOL_COUNT) return toolCalls;
    // Show last VISIBLE_TOOL_COUNT tools
    return toolCalls.slice(total - VISIBLE_TOOL_COUNT);
  }, [toolCalls, showAll, total]);

  // Offset for mapping visible indices back to original indices
  const offset = showAll || total <= VISIBLE_TOOL_COUNT ? 0 : total - VISIBLE_TOOL_COUNT;

  return (
    <div className="ai-chat-tools">
      {/* Show "N earlier tools" toggle when collapsed */}
      {!showAll && hiddenCount > 0 && (
        <button className="ai-chat-tools-toggle" onClick={() => setShowAll(true)}>
          {'\u25B6'} {hiddenCount} earlier tool{hiddenCount > 1 ? 's' : ''}{isStreaming ? '' : ` \u2014 click to expand`}
        </button>
      )}
      {/* Show collapse toggle when expanded and there are many tools */}
      {showAll && hiddenCount > 0 && (
        <button className="ai-chat-tools-toggle" onClick={() => setShowAll(false)}>
          {'\u25BC'} Collapse — showing all {total} tools
        </button>
      )}
      {visibleTools.map((tc, vi) => {
        const ti = offset + vi;
        return (
          <div key={ti} className={`ai-chat-tool-card${!tc.result && isStreaming ? ' running' : ''}`}>
            <button
              className="ai-chat-tool-header"
              onClick={() => onToggle(msgIdx, ti)}
            >
              <span className="ai-chat-tool-icon">{tc.result ? '\u2713' : '\u25B6'}</span>
              <span className="ai-chat-tool-name">{tc.name.replace(/_/g, ' ')}</span>
              <span className="ai-chat-tool-toggle">{tc.expanded ? '\u25B4' : '\u25BE'}</span>
            </button>
            {tc.expanded && (
              <div className="ai-chat-tool-detail">
                <div className="ai-chat-tool-section">
                  <span className="ai-chat-tool-section-label">Args</span>
                  <pre>{JSON.stringify(tc.arguments, null, 2)}</pre>
                </div>
                {tc.result && (
                  <div className="ai-chat-tool-section">
                    <span className="ai-chat-tool-section-label">Result</span>
                    <pre>{(() => {
                      try { return JSON.stringify(JSON.parse(tc.result), null, 2); } catch { return tc.result; }
                    })()}</pre>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface AIChatPanelProps {
  onCollapse: () => void;
  dragHandleProps?: Record<string, unknown>;
  panelIcon?: string;
  sliceContext?: string;
  onSliceChanged?: () => void;
  fullScreen?: boolean;
  /** Persist chat state across remounts — provide a stable id */
  persistId?: string;
  /** Show a pop-out button in the header */
  showPopout?: boolean;
}

export default function AIChatPanel({ onCollapse, dragHandleProps, panelIcon, sliceContext, onSliceChanged, fullScreen, persistId, showPopout }: AIChatPanelProps) {
  // Force-update trigger for store-driven re-renders
  const [, bump] = useState(0);
  const store = persistId ? getStore(persistId) : null;

  // --- Local state (used when no persistId) ---
  const [localMessages, setLocalMessages] = useState<ChatMessage[]>([]);
  const [localStreaming, setLocalStreaming] = useState(false);
  const [localError, setLocalError] = useState('');
  const localAbortRef = useRef<AbortController | null>(null);
  const localReqIdRef = useRef('');
  const localDidMutateRef = useRef(false);

  // --- Common state ---
  const [input, setInput] = useState('');
  const [hasKey, setHasKey] = useState<boolean | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState(store?.selectedModel || '');
  const [selectedAgent, setSelectedAgent] = useState(store?.selectedAgent || '');
  const [agents, setAgents] = useState<ChatAgent[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Effective state: read from store if persistent, local state otherwise
  const messages = store ? store.messages : localMessages;
  const streaming = store ? store.streaming : localStreaming;
  const error = store ? store.error : localError;

  // Subscribe to store updates
  useEffect(() => {
    if (!store) return;
    store.listener = () => bump(n => n + 1);
    return () => { if (store.listener) store.listener = null; };
  }, [store]);

  // Sync model/agent selection back to store
  useEffect(() => {
    if (store) {
      store.selectedModel = selectedModel;
      store.selectedAgent = selectedAgent;
    }
  }, [store, selectedModel, selectedAgent]);

  // Drain pending slice refresh when component is mounted
  useEffect(() => {
    if (store?.pendingSliceRefresh && onSliceChanged) {
      store.pendingSliceRefresh = false;
      onSliceChanged();
    }
  });

  useEffect(() => {
    getConfig().then(s => setHasKey(!!s.ai_api_key_set)).catch(() => setHasKey(false));
    getAiModels().then(data => {
      setModels(data.models || []);
      if (!store?.selectedModel) {
        setSelectedModel(data.default || data.models?.[0] || '');
      }
    }).catch(() => {});
    getChatAgents().then(setAgents).catch(() => {});
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // --- Send ---
  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput('');

    const userMsg: ChatMessage = { role: 'user', content: text };

    if (store && persistId) {
      // Persistent mode: delegate to module-level stream runner
      store.messages = [...store.messages, userMsg];
      store.listener?.();
      const apiMessages = store.messages
        .filter(m => m.role === 'user' || m.role === 'assistant')
        .map(m => ({ role: m.role as string, content: m.content }));
      runModuleStream(persistId, apiMessages, selectedModel, selectedAgent, sliceContext || undefined);
    } else {
      // Local mode: run stream in component (original behavior)
      const newMessages = [...localMessages, userMsg];
      setLocalMessages(newMessages);
      setLocalStreaming(true);
      setLocalError('');
      localDidMutateRef.current = false;

      const reqId = `chat-${Date.now()}`;
      localReqIdRef.current = reqId;
      const controller = new AbortController();
      localAbortRef.current = controller;

      setLocalMessages(prev => [...prev, { role: 'assistant', content: '', toolCalls: [] }]);
      let currentToolCalls: ToolCall[] = [];

      try {
        const apiMessages = newMessages
          .filter(m => m.role === 'user' || m.role === 'assistant')
          .map(m => ({ role: m.role as string, content: m.content }));

        for await (const chunk of streamChat(apiMessages, selectedModel, {
          agent: selectedAgent || undefined,
          sliceContext: sliceContext || undefined,
          requestId: reqId,
          signal: controller.signal,
        })) {
          if (chunk.error) {
            setLocalError(chunk.error);
            setLocalMessages(prev => {
              const last = prev[prev.length - 1];
              if (last?.role === 'assistant' && !last.content && (!last.toolCalls || last.toolCalls.length === 0)) return prev.slice(0, -1);
              return prev;
            });
            break;
          }
          if ((chunk as any).tool_call) {
            const tc = (chunk as any).tool_call;
            currentToolCalls = [...currentToolCalls, { name: tc.name, arguments: tc.arguments }];
            if (MUTATING_TOOLS.has(tc.name)) localDidMutateRef.current = true;
            setLocalMessages(prev => {
              const u = [...prev]; const l = u[u.length - 1];
              if (l?.role === 'assistant') u[u.length - 1] = { ...l, toolCalls: [...currentToolCalls] };
              return u;
            });
            continue;
          }
          if ((chunk as any).tool_result) {
            const tr = (chunk as any).tool_result;
            currentToolCalls = currentToolCalls.map(tc => tc.name === tr.name && !tc.result ? { ...tc, result: tr.result } : tc);
            setLocalMessages(prev => {
              const u = [...prev]; const l = u[u.length - 1];
              if (l?.role === 'assistant') u[u.length - 1] = { ...l, toolCalls: [...currentToolCalls] };
              return u;
            });
            continue;
          }
          if (chunk.content) {
            setLocalMessages(prev => {
              const u = [...prev]; const l = u[u.length - 1];
              if (l?.role === 'assistant') u[u.length - 1] = { ...l, content: l.content + chunk.content };
              return u;
            });
          }
          if (chunk.done) break;
        }
      } catch (e: any) {
        if (e.name !== 'AbortError') {
          setLocalError(e.message || 'Stream failed');
          setLocalMessages(prev => {
            const last = prev[prev.length - 1];
            if (last?.role === 'assistant' && !last.content && (!last.toolCalls || last.toolCalls.length === 0)) return prev.slice(0, -1);
            return prev;
          });
        }
      } finally {
        setLocalStreaming(false);
        localAbortRef.current = null;
        localReqIdRef.current = '';
        if (localDidMutateRef.current && onSliceChanged) onSliceChanged();
      }
    }
  }, [input, messages, streaming, selectedModel, selectedAgent, sliceContext, onSliceChanged, store, persistId, localMessages]);

  const handleStop = useCallback(() => {
    if (store && persistId) {
      stopModuleStream(persistId);
    } else {
      if (localAbortRef.current) localAbortRef.current.abort();
      if (localReqIdRef.current) stopChatStream(localReqIdRef.current).catch(() => {});
      setLocalStreaming(false);
    }
  }, [store, persistId]);

  const handleClear = useCallback(() => {
    if (store && persistId) {
      clearModuleChat(persistId);
    } else {
      if (localStreaming) handleStop();
      setLocalMessages([]);
      setLocalError('');
    }
  }, [store, persistId, localStreaming, handleStop]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  }, [handleSend]);

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }, []);

  const toggleToolExpanded = useCallback((msgIdx: number, toolIdx: number) => {
    if (store) {
      const msgs = [...store.messages];
      const msg = msgs[msgIdx];
      if (msg?.toolCalls) {
        const tcs = [...msg.toolCalls];
        tcs[toolIdx] = { ...tcs[toolIdx], expanded: !tcs[toolIdx].expanded };
        msgs[msgIdx] = { ...msg, toolCalls: tcs };
        store.messages = msgs;
        store.listener?.();
      }
    } else {
      setLocalMessages(prev => {
        const updated = [...prev];
        const msg = updated[msgIdx];
        if (msg?.toolCalls) {
          const tcs = [...msg.toolCalls];
          tcs[toolIdx] = { ...tcs[toolIdx], expanded: !tcs[toolIdx].expanded };
          updated[msgIdx] = { ...msg, toolCalls: tcs };
        }
        return updated;
      });
    }
  }, [store]);

  if (hasKey === false) {
    return (
      <div className={`ai-chat-panel${fullScreen ? ' ai-chat-fullscreen' : ''}`}>
        <div className="ai-chat-header" {...(fullScreen ? {} : dragHandleProps)}>
          {panelIcon && !fullScreen && <span style={{ cursor: 'grab' }}>{panelIcon}</span>}
          <span className="ai-chat-header-icon">AI</span>
          <span className="ai-chat-header-title">LoomAI</span>
          {showPopout && <button className="ai-chat-popout-btn" onClick={() => window.open('/popout?tool=loomai', '_blank')} title="Open in new tab"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></svg></button>}
          {!fullScreen && <button className="ai-chat-collapse-btn" onClick={onCollapse} title="Collapse">{'\u2715'}</button>}
        </div>
        <div className="ai-chat-no-key">
          <span style={{ fontSize: 24 }}>{'\u26A0'}</span>
          <span>FABRIC API key required</span>
          <span style={{ fontSize: 11, opacity: 0.7 }}>Configure your API key in Settings to use AI chat</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`ai-chat-panel${fullScreen ? ' ai-chat-fullscreen' : ''}`} data-help-id="ai-chat.panel">
      <div className="ai-chat-header" data-help-id="ai-chat.panel" {...(fullScreen ? {} : dragHandleProps)}>
        {panelIcon && !fullScreen && <span style={{ cursor: 'grab' }}>{panelIcon}</span>}
        <span className="ai-chat-header-icon">AI</span>
        <span className="ai-chat-header-title">LoomAI</span>
        <button className="ai-chat-new-btn" onClick={handleClear} title="New chat" data-help-id="ai-chat.clear">{'\u21BA'}</button>
        {showPopout && <button className="ai-chat-popout-btn" onClick={() => window.open('/popout?tool=loomai', '_blank')} title="Open in new tab"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></svg></button>}
        {!fullScreen && <button className="ai-chat-collapse-btn" onClick={onCollapse} title="Collapse">{'\u2715'}</button>}
      </div>

      <div className="ai-chat-config">
        <select className="ai-chat-select" value={selectedModel} onChange={e => setSelectedModel(e.target.value)} title="Model" data-help-id="ai-chat.model" disabled={streaming}>
          {models.length === 0 && <option value="">Loading...</option>}
          {models.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        <select className="ai-chat-select" value={selectedAgent} onChange={e => setSelectedAgent(e.target.value)} title="Agent persona" data-help-id="ai-chat.agent" disabled={streaming}>
          <option value="">General</option>
          {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      </div>

      <div className="ai-chat-messages">
        {messages.length === 0 && !error && (
          <div className="ai-chat-empty">
            <div className="ai-chat-empty-icon">{'\u2728'}</div>
            <div className="ai-chat-empty-text">
              Ask about your slice, FABRIC resources, or tell me to create and deploy experiments.
              {sliceContext && <><br /><strong>Slice context active</strong> — I can see your topology.</>}
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`ai-chat-msg ${msg.role === 'user' ? 'user' : 'assistant'}`}>
            <span className="ai-chat-msg-role">{msg.role === 'user' ? 'You' : 'AI'}</span>
            <div className="ai-chat-msg-bubble">
              {msg.toolCalls && msg.toolCalls.length > 0 && (
                <ToolCallsView
                  toolCalls={msg.toolCalls}
                  msgIdx={i}
                  onToggle={toggleToolExpanded}
                  isStreaming={streaming && i === messages.length - 1}
                />
              )}
              {msg.role === 'user' ? (
                msg.content
              ) : (
                <>
                  {msg.content && <ReactMarkdown>{msg.content}</ReactMarkdown>}
                  {streaming && i === messages.length - 1 && !msg.content && msg.toolCalls && msg.toolCalls.length > 0 && !msg.toolCalls[msg.toolCalls.length - 1].result && (
                    <div className="ai-chat-tool-running">Running tool...</div>
                  )}
                  {streaming && i === messages.length - 1 && (msg.content || (msg.toolCalls && msg.toolCalls.every(tc => tc.result))) && <span className="ai-chat-streaming" />}
                </>
              )}
            </div>
          </div>
        ))}
        {error && <div className="ai-chat-error">{error}</div>}
        <div ref={messagesEndRef} />
      </div>

      <div className="ai-chat-input-area">
        <textarea
          className="ai-chat-input"
          value={input}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          placeholder={streaming ? 'Working...' : 'Ask about FABRIC...'}
          disabled={streaming}
          rows={1}
        />
        {streaming ? (
          <button className="ai-chat-stop-btn" onClick={handleStop} title="Stop" data-help-id="ai-chat.stop">{'\u25A0'}</button>
        ) : (
          <button className="ai-chat-send-btn" onClick={handleSend} disabled={!input.trim()} title="Send (Enter)" data-help-id="ai-chat.send">{'\u2191'}</button>
        )}
      </div>
    </div>
  );
}
