'use client';
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import { getAiModels, getDefaultModel, setDefaultModel as apiSetDefaultModel, refreshAiModels, getChatAgents, streamChat, stopChatStream, getConfig } from '../api/client';
import type { ChatAgent } from '../api/client';
import '../styles/ai-chat-panel.css';

const VISIBLE_TOOL_COUNT = 3;

interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
  result?: string;
  summary?: string;
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
  /** Tool limit was reached — show Continue button */
  toolLimitReached: boolean;
  /** Epoch ms when the current stream started; null when not streaming */
  streamStartTime: number | null;
}

const _stores = new Map<string, ChatStore>();

function getStore(id: string): ChatStore {
  let s = _stores.get(id);
  if (!s) {
    // Restore messages from localStorage if available
    let savedMessages: ChatMessage[] = [];
    try {
      const saved = localStorage.getItem(`loomai-chat-${id}`);
      if (saved) savedMessages = JSON.parse(saved);
    } catch { /* ignore */ }

    // Restore saved model preference
    let savedModel = '';
    try {
      savedModel = localStorage.getItem('loomai-chat-selected-model') || '';
    } catch { /* ignore */ }

    s = {
      messages: savedMessages, selectedModel: savedModel, selectedAgent: '',
      streaming: false, error: '', abortController: null,
      requestId: '', didMutate: false, listener: null,
      pendingSliceRefresh: false, toolLimitReached: false,
      streamStartTime: null,
    };
    _stores.set(id, s);
  }
  return s;
}

function _persistMessages(id: string, messages: ChatMessage[]) {
  try {
    // Keep last 50 messages to avoid bloating localStorage
    const toSave = messages.slice(-50).map(m => ({ role: m.role, content: m.content }));
    localStorage.setItem(`loomai-chat-${id}`, JSON.stringify(toSave));
  } catch { /* storage full or unavailable */ }
}

// ---------------------------------------------------------------------------
// Conversation list management (persisted to localStorage)
// ---------------------------------------------------------------------------

interface ConversationMeta {
  id: string;
  name: string;
  createdAt: number;
}

const CONV_LIST_KEY = 'loomai-conversations';
const ACTIVE_CONV_KEY = 'loomai-active-conversation';

function _loadConversations(): ConversationMeta[] {
  try {
    const raw = localStorage.getItem(CONV_LIST_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function _saveConversations(convs: ConversationMeta[]) {
  try { localStorage.setItem(CONV_LIST_KEY, JSON.stringify(convs)); } catch { /* ignore */ }
}

function _getActiveConvId(): string {
  try { return localStorage.getItem(ACTIVE_CONV_KEY) || ''; } catch { return ''; }
}

function _setActiveConvId(id: string) {
  try { localStorage.setItem(ACTIVE_CONV_KEY, id); } catch { /* ignore */ }
}

function _ensureDefaultConversation(): { convs: ConversationMeta[]; activeId: string } {
  let convs = _loadConversations();
  let activeId = _getActiveConvId();
  if (convs.length === 0) {
    const defaultConv: ConversationMeta = { id: 'default', name: 'Chat 1', createdAt: Date.now() };
    convs = [defaultConv];
    activeId = 'default';
    _saveConversations(convs);
    _setActiveConvId(activeId);
  }
  if (!activeId || !convs.find(c => c.id === activeId)) {
    activeId = convs[0].id;
    _setActiveConvId(activeId);
  }
  return { convs, activeId };
}

const MUTATING_TOOLS = new Set([
  'create_slice', 'add_node', 'add_component', 'add_network',
  'submit_slice', 'delete_slice', 'renew_slice', 'load_template',
  'save_as_template', 'remove_node', 'remove_network',
]);

/** Format elapsed ms as "M:SS" (or "H:MM:SS" for long sessions) for the progress strip. */
function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  if (h > 0) return `${h}:${mm.toString().padStart(2, '0')}:${ss.toString().padStart(2, '0')}`;
  return `${mm}:${ss.toString().padStart(2, '0')}`;
}

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
  store.streamStartTime = Date.now();

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
          tc.name === tr.name && !tc.result ? { ...tc, result: tr.result, summary: tr.summary } : tc
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

      // Warning (context nearly full, etc.)
      if ((chunk as any).warning) {
        store.messages = [...store.messages, { role: 'system' as any, content: `⚠️ ${(chunk as any).warning}` }];
        store.listener?.();
      }

      // Usage stats (token count, tool calls, duration)
      if ((chunk as any).usage) {
        const u = (chunk as any).usage;
        const msgs = [...store.messages];
        const last = msgs[msgs.length - 1];
        if (last?.role === 'assistant') {
          const usageText = `\n\n---\n*~${u.tokens} tokens, ${u.tool_calls} tool calls, ${(u.duration_ms / 1000).toFixed(1)}s*`;
          msgs[msgs.length - 1] = { ...last, content: last.content + usageText };
          store.messages = msgs;
          store.listener?.();
        }
      }

      // Tool limit reached — flag for Continue button
      if ((chunk as any).tool_limit_reached) {
        store.toolLimitReached = true;
        store.listener?.();
      }

      // Execution progress (LoomAI-side tool execution)
      if ((chunk as any).execution_progress) {
        const msgs = [...store.messages];
        const last = msgs[msgs.length - 1];
        if (last?.role === 'assistant') {
          const progress = `*${(chunk as any).execution_progress}*\n`;
          msgs[msgs.length - 1] = { ...last, content: last.content + progress };
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
    store.streamStartTime = null;
    if (store.didMutate) store.pendingSliceRefresh = true;
    _persistMessages(storeId, store.messages);
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
              <span className="ai-chat-tool-step">{ti + 1}.</span>
              <span className="ai-chat-tool-icon">{tc.result ? '\u2713' : isStreaming ? '\u23F3' : '\u25B6'}</span>
              <span className={`ai-chat-tool-name${MUTATING_TOOLS.has(tc.name) ? ' mutating' : ''}`}>{tc.name.replace(/_/g, ' ')}</span>
              {tc.summary && <span className="ai-chat-tool-summary">{'\u2014'} {tc.summary}</span>}
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

function formatModelLabel(m: {id: string; healthy?: boolean; context_length?: number; tier?: string; supports_tools?: boolean}, isDefault: boolean): string {
  const ctx = m.context_length;
  const ctxLabel = ctx ? (ctx >= 100000 ? '128K+' : ctx >= 30000 ? '32K' : ctx >= 12000 ? '16K' : '8K') : '';
  const badges: string[] = [];
  if (ctxLabel) badges.push(ctxLabel);
  // Speed tier from backend profile
  const tierLabel = m.tier === 'compact' ? 'fast' : m.tier === 'large' ? 'powerful' : '';
  if (tierLabel) badges.push(tierLabel);
  if (m.supports_tools) badges.push('tools');
  const badgeStr = badges.length ? ` [${badges.join(', ')}]` : '';
  const star = isDefault ? ' \u2605' : '';
  const unavail = m.healthy === false ? ' (unavailable)' : '';
  return `${m.id}${badgeStr}${star}${unavail}`;
}

export default React.memo(function AIChatPanel({ onCollapse, dragHandleProps, panelIcon, sliceContext, onSliceChanged, fullScreen, persistId, showPopout }: AIChatPanelProps) {
  // Force-update trigger for store-driven re-renders
  const [, bump] = useState(0);

  // --- Conversation management ---
  const [conversations, setConversations] = useState<ConversationMeta[]>(() => _ensureDefaultConversation().convs);
  const [activeConvId, setActiveConvId] = useState<string>(() => _ensureDefaultConversation().activeId);

  // Use conversation ID as store key (falls back to persistId for backward compat)
  const storeKey = persistId ? `conv-${activeConvId}` : null;
  const store = storeKey ? getStore(storeKey) : null;

  const handleSwitchConversation = useCallback((id: string) => {
    setActiveConvId(id);
    _setActiveConvId(id);
  }, []);

  const handleDeleteConversation = useCallback((id: string) => {
    const updated = conversations.filter(c => c.id !== id);
    // Clean up localStorage for this conversation
    try { localStorage.removeItem(`loomai-chat-conv-${id}`); } catch { /* ignore */ }
    _stores.delete(`conv-${id}`);
    if (updated.length === 0) {
      const defaultConv: ConversationMeta = { id: 'default', name: 'Chat 1', createdAt: Date.now() };
      updated.push(defaultConv);
    }
    setConversations(updated);
    _saveConversations(updated);
    if (id === activeConvId) {
      setActiveConvId(updated[0].id);
      _setActiveConvId(updated[0].id);
    }
  }, [conversations, activeConvId]);

  // --- Local state (used when no persistId) ---
  const [localMessages, setLocalMessages] = useState<ChatMessage[]>([]);
  const [localStreaming, setLocalStreaming] = useState(false);
  const [localError, setLocalError] = useState('');
  const localAbortRef = useRef<AbortController | null>(null);
  const localReqIdRef = useRef('');
  const localDidMutateRef = useRef(false);
  const localStreamStartRef = useRef<number | null>(null);

  // --- Common state ---
  const [input, setInput] = useState('');
  // Command history (up/down arrow navigation)
  const historyRef = useRef<string[]>([]);
  if (historyRef.current.length === 0) {
    try { historyRef.current = JSON.parse(localStorage.getItem('loomai-chat-history') || '[]'); } catch {}
  }
  const historyIndexRef = useRef(-1);
  const savedInputRef = useRef(''); // saves current input when browsing history
  const [hasKey, setHasKey] = useState<boolean | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [fabricModels, setFabricModels] = useState<Array<{id: string; healthy?: boolean; context_length?: number; tier?: string; supports_tools?: boolean}>>([]);
  const [nrpModels, setNrpModels] = useState<Array<{id: string; healthy?: boolean; context_length?: number; tier?: string; supports_tools?: boolean}>>([]);
  const [defaultModel, setDefaultModel] = useState('');
  const [hasProviderKey, setHasProviderKey] = useState<{fabric: boolean; nrp: boolean}>({fabric: false, nrp: false});
  const [customModels, setCustomModels] = useState<Record<string, Array<{id: string; healthy?: boolean}>>>({});
  const [showKeyModal, setShowKeyModal] = useState<'fabric' | 'nrp' | null>(null);
  const [refreshingModels, setRefreshingModels] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState('');
  const [selectedModel, setSelectedModel] = useState(store?.selectedModel || '');
  const selectedModelRef = useRef(selectedModel);
  useEffect(() => { selectedModelRef.current = selectedModel; }, [selectedModel]);
  const [selectedAgent, setSelectedAgent] = useState(store?.selectedAgent || '');
  const [agents, setAgents] = useState<ChatAgent[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Effective state: read from store if persistent, local state otherwise
  const messages = store ? store.messages : localMessages;
  const streaming = store ? store.streaming : localStreaming;
  const error = store ? store.error : localError;
  const toolLimitReached = store ? store.toolLimitReached : false;

  // Live-updating elapsed time for the progress strip — ticks every 1s while
  // streaming so users can see how long a long tool-calling session has been
  // running without scrolling through the tool card list.
  const [elapsedMs, setElapsedMs] = useState(0);
  useEffect(() => {
    if (!streaming) { setElapsedMs(0); return; }
    const getStart = () => (store ? store.streamStartTime : localStreamStartRef.current);
    const tick = () => {
      const start = getStart();
      setElapsedMs(start ? Date.now() - start : 0);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [streaming, store]);

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

    // Fast path: get the first healthy model immediately so chat is usable
    if (!store?.selectedModel) {
      getDefaultModel().then(data => {
        if (data.default && !selectedModel) {
          setSelectedModel(data.default);
          try { localStorage.setItem('loomai-chat-selected-model', data.default); } catch { /* ignore */ }
        }
      }).catch(() => {});
    }

    // Full model list with health checks (slower — loads in background)
    getAiModels().then(data => {
      const fab = (data.fabric || []).map((m: any) => ({ id: m.id || m, healthy: m.healthy !== false, context_length: m.context_length, tier: m.tier, supports_tools: m.supports_tools }));
      const nrp = (data.nrp || []).map((m: any) => ({ id: m.id || m, healthy: m.healthy !== false, context_length: m.context_length, tier: m.tier, supports_tools: m.supports_tools }));
      setDefaultModel(data.default || '');
      setFabricModels(fab);
      setNrpModels(nrp);
      setHasProviderKey(data.has_key || {fabric: false, nrp: false});
      // Custom providers
      const custom = (data as any).custom || {};
      const customParsed: Record<string, Array<{id: string; healthy?: boolean}>> = {};
      for (const [name, models] of Object.entries(custom)) {
        customParsed[name] = ((models as any[]) || []).map((m: any) => ({ id: m.id || m, healthy: m.healthy !== false }));
      }
      setCustomModels(customParsed);
      // Flat list for internal use
      const customIds = Object.entries(customParsed).flatMap(([name, ms]) => ms.map(m => `${name}:${m.id}`));
      setModels([...fab.map(m => m.id), ...nrp.map(m => `nrp:${m.id}`), ...customIds]);
      if (!store?.selectedModel && !selectedModel) {
        const fallback = data.default || fab.find(m => m.healthy)?.id || fab[0]?.id || '';
        setSelectedModel(fallback);
        if (fallback) { try { localStorage.setItem('loomai-chat-selected-model', fallback); } catch { /* ignore */ } }
      }
    }).catch(() => {});
    getChatAgents().then(setAgents).catch(() => {});

    // Poll for external model changes (e.g., CLI /model command) every 30s.
    // Only update if the *backend default* changed (not if local selection differs).
    let lastKnownDefault = '';
    getDefaultModel().then(d => { lastKnownDefault = d.default || ''; }).catch(() => {});
    const pollInterval = setInterval(() => {
      getDefaultModel().then(data => {
        const backendDefault = data.default || '';
        if (backendDefault && backendDefault !== lastKnownDefault) {
          // Backend default changed externally (CLI /model, startup discovery)
          lastKnownDefault = backendDefault;
          setSelectedModel(backendDefault);
          try { localStorage.setItem('loomai-chat-selected-model', backendDefault); } catch { /* ignore */ }
        }
      }).catch(() => {});
    }, 30_000);
    return () => clearInterval(pollInterval);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // --- Continue after tool limit ---
  const handleContinue = useCallback(() => {
    if (!store || !storeKey || streaming) return;
    store.toolLimitReached = false;
    // Send a continuation message
    const continueMsg: ChatMessage = { role: 'user', content: 'Continue where you left off.' };
    store.messages = [...store.messages, continueMsg];
    store.listener?.();
    const apiMessages = store.messages
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map(m => ({ role: m.role as string, content: m.content }));
    runModuleStream(storeKey, apiMessages, selectedModel, selectedAgent, sliceContext || undefined);
  }, [store, storeKey, streaming, selectedModel, selectedAgent, sliceContext]);

  // --- Send ---
  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput('');

    // Save to command history (persist to localStorage)
    const history = historyRef.current;
    if (text && (history.length === 0 || history[history.length - 1] !== text)) {
      history.push(text);
      // Keep last 100 entries
      if (history.length > 100) history.splice(0, history.length - 100);
      try { localStorage.setItem('loomai-chat-history', JSON.stringify(history)); } catch {}
    }
    historyIndexRef.current = -1;
    savedInputRef.current = '';

    const userMsg: ChatMessage = { role: 'user', content: text };

    if (store && storeKey) {
      // Persistent mode: delegate to module-level stream runner
      store.toolLimitReached = false;
      store.messages = [...store.messages, userMsg];
      store.listener?.();
      const apiMessages = store.messages
        .filter(m => m.role === 'user' || m.role === 'assistant')
        .map(m => ({ role: m.role as string, content: m.content }));
      runModuleStream(storeKey, apiMessages, selectedModel, selectedAgent, sliceContext || undefined);
    } else {
      // Local mode: run stream in component (original behavior)
      const newMessages = [...localMessages, userMsg];
      setLocalMessages(newMessages);
      setLocalStreaming(true);
      setLocalError('');
      localDidMutateRef.current = false;
      localStreamStartRef.current = Date.now();

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
        localStreamStartRef.current = null;
        if (localDidMutateRef.current && onSliceChanged) onSliceChanged();
      }
    }
  }, [input, messages, streaming, selectedModel, selectedAgent, sliceContext, onSliceChanged, store, storeKey, localMessages]);

  const handleStop = useCallback(() => {
    if (store && storeKey) {
      stopModuleStream(storeKey);
    } else {
      if (localAbortRef.current) localAbortRef.current.abort();
      if (localReqIdRef.current) stopChatStream(localReqIdRef.current).catch(() => {});
      setLocalStreaming(false);
    }
  }, [store, storeKey]);

  const handleClear = useCallback(() => {
    if (store && storeKey) {
      clearModuleChat(storeKey);
    } else {
      if (localStreaming) handleStop();
      setLocalMessages([]);
      setLocalError('');
    }
  }, [store, storeKey, localStreaming, handleStop]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); return; }

    const history = historyRef.current;
    if (e.key === 'ArrowUp' && history.length > 0) {
      e.preventDefault();
      if (historyIndexRef.current === -1) {
        savedInputRef.current = input; // save current input before browsing
      }
      const newIdx = Math.min(historyIndexRef.current + 1, history.length - 1);
      historyIndexRef.current = newIdx;
      setInput(history[history.length - 1 - newIdx]);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (historyIndexRef.current <= 0) {
        historyIndexRef.current = -1;
        setInput(savedInputRef.current);
      } else {
        historyIndexRef.current -= 1;
        setInput(history[history.length - 1 - historyIndexRef.current]);
      }
    }
  }, [handleSend, input]);

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
          {panelIcon && !fullScreen && <span style={{ cursor: 'grab' }}>{panelIcon === '__loomai_icon__' ? <img src="/loomai-icon-transparent.svg" alt="" style={{ height: 14 }} /> : panelIcon}</span>}
          <img src="/loomai-icon-transparent.svg" alt="" className="ai-chat-header-icon-img" />
          <img src="/loomai-wordmark-transparent-light-ink-trimmed.svg" alt="LoomAI" className="ai-chat-header-wordmark ai-chat-wordmark-light" />
          <img src="/loomai-wordmark-transparent-dark-ink-trimmed.svg" alt="LoomAI" className="ai-chat-header-wordmark ai-chat-wordmark-dark" />
          {showPopout && <button className="ai-chat-popout-btn" onClick={() => window.open('/popout?tool=loomai', '_blank')} title="Open in new tab"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></svg></button>}
          {!fullScreen && <button className="ai-chat-collapse-btn" onClick={onCollapse} title="Collapse">{'\u2715'}</button>}
        </div>
        <div className="ai-chat-no-key">
          <span style={{ fontSize: 24 }}>{'\u26A0'}</span>
          <span>FABRIC API key required</span>
          <span style={{ fontSize: 11, opacity: 0.7 }}>Configure your API key in Settings to use LoomAI assistant</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`ai-chat-panel${fullScreen ? ' ai-chat-fullscreen' : ''}`} data-help-id="ai-chat.panel">
      <div className="ai-chat-header" data-help-id="ai-chat.panel" {...(fullScreen ? {} : dragHandleProps)}>
        {panelIcon && !fullScreen && <span style={{ cursor: 'grab' }}>{panelIcon === '__loomai_icon__' ? <img src="/loomai-icon-transparent.svg" alt="" style={{ height: 14 }} /> : panelIcon}</span>}
        <img src="/loomai-wordmark-transparent-light-ink-trimmed.svg" alt="LoomAI" className="ai-chat-header-wordmark ai-chat-wordmark-light" />
        <img src="/loomai-wordmark-transparent-dark-ink-trimmed.svg" alt="LoomAI" className="ai-chat-header-wordmark ai-chat-wordmark-dark" />
        <button className="ai-chat-new-btn" onClick={handleClear} title="Clear current chat">{'\u21BA'}</button>
        {showPopout && <button className="ai-chat-popout-btn" onClick={() => window.open('/popout?tool=loomai', '_blank')} title="Open in new tab"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></svg></button>}
        {!fullScreen && <button className="ai-chat-collapse-btn" onClick={onCollapse} title="Collapse">{'\u2715'}</button>}
      </div>

      <div className="ai-chat-config">
        <select className="ai-chat-select" value={selectedModel} onChange={e => {
          const val = e.target.value;
          const isNrp = nrpModels.some(m => m.id === val.replace('nrp:', ''));
          const isFabric = fabricModels.some(m => m.id === val);
          if (isFabric && !hasProviderKey.fabric) { setShowKeyModal('fabric'); return; }
          if (isNrp && !hasProviderKey.nrp) { setShowKeyModal('nrp'); return; }
          setSelectedModel(val);
          try { localStorage.setItem('loomai-chat-selected-model', val); } catch { /* ignore */ }
          apiSetDefaultModel(val).catch(() => { /* best-effort */ });
        }} title="Model" data-help-id="ai-chat.model" disabled={streaming}>
          {fabricModels.length === 0 && nrpModels.length === 0 && <option value="">Loading...</option>}
          {fabricModels.length > 0 && (
            <optgroup label="FABRIC AI Models">
              {fabricModels.map(m => (
                <option key={m.id} value={m.id} disabled={!m.healthy}>
                  {formatModelLabel(m, m.id === defaultModel)}{m.healthy === false ? ' (down)' : ''}
                </option>
              ))}
            </optgroup>
          )}
          {nrpModels.length > 0 && (
            <optgroup label="NRP/Nautilus Models">
              {nrpModels.map(m => (
                <option key={`nrp:${m.id}`} value={`nrp:${m.id}`} disabled={!m.healthy}>
                  {formatModelLabel(m, m.id === defaultModel)}{m.healthy === false ? ' (down)' : ''}
                </option>
              ))}
            </optgroup>
          )}
          {Object.entries(customModels).map(([name, ms]) => ms.length > 0 && (
            <optgroup key={name} label={`${name} Models`}>
              {ms.map(m => (
                <option key={`${name}:${m.id}`} value={`${name}:${m.id}`} disabled={!m.healthy}>
                  {formatModelLabel(m, false)}{m.healthy === false ? ' (down)' : ''}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <button
          className="ai-chat-refresh-models-btn"
          onClick={async () => {
            setRefreshingModels(true);
            setRefreshMsg('');
            try {
              const result = await refreshAiModels();
              setRefreshMsg(result.message || 'Models up to date');
              // Reload model list
              const data = await getAiModels();
              setFabricModels(data.fabric || []);
              setNrpModels(data.nrp || []);
              setCustomModels(data.custom || {});
              setHasProviderKey(data.has_key || { fabric: false, nrp: false });
              if (data.default) setDefaultModel(data.default);
            } catch (e: any) {
              setRefreshMsg(`Refresh failed: ${e.message}`);
            } finally {
              setRefreshingModels(false);
              setTimeout(() => setRefreshMsg(''), 5000);
            }
          }}
          disabled={refreshingModels || streaming}
          title="Refresh model list from FABRIC AI and NRP"
          style={{ marginLeft: 4, padding: '2px 8px', fontSize: 11, cursor: refreshingModels ? 'wait' : 'pointer' }}
        >
          {refreshingModels ? '\u21BB...' : '\u21BB'}
        </button>
        {refreshMsg && <span style={{ fontSize: 10, color: 'var(--fabric-text-muted)', marginLeft: 6 }}>{refreshMsg}</span>}
      </div>

      <div className="ai-chat-messages">
        {messages.length === 0 && !error && (
          <div className="ai-chat-empty">
            <div className="ai-chat-empty-icon"><img src="/loomai-icon-transparent.svg" alt="" style={{ height: 32, opacity: 0.5 }} /></div>
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
              {streaming && i === messages.length - 1 && msg.toolCalls && msg.toolCalls.length > 0 && (() => {
                const running = [...msg.toolCalls].reverse().find(tc => !tc.result);
                const n = msg.toolCalls.length;
                return (
                  <div className="ai-chat-progress-strip" role="status" aria-live="polite">
                    <span className="ai-chat-progress-count">
                      ⏳ {n} tool call{n === 1 ? '' : 's'}
                    </span>
                    <span className="ai-chat-progress-elapsed">{formatElapsed(elapsedMs)}</span>
                    {running && (
                      <span className="ai-chat-progress-current" title={running.name}>
                        ▸ {running.name}
                      </span>
                    )}
                  </div>
                );
              })()}
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

      {toolLimitReached && !streaming && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '6px 12px', borderTop: '1px solid var(--border-color, #333)' }}>
          <button
            className="btn btn-primary"
            onClick={handleContinue}
            style={{ fontSize: 12, padding: '4px 16px' }}
          >
            Continue
          </button>
        </div>
      )}

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

      {/* API key modal — shown when user selects a model from a provider without a key */}
      {showKeyModal && (
        <div className="ai-chat-key-modal-overlay" onClick={() => setShowKeyModal(null)}>
          <div className="ai-chat-key-modal" onClick={e => e.stopPropagation()}>
            <h3>API Key Required</h3>
            <p>
              {showKeyModal === 'fabric' ? (
                <>
                  A <strong>FABRIC AI API key</strong> is required to use FABRIC AI models.
                  All FABRIC testbed users are eligible for a free API key.
                </>
              ) : (
                <>
                  An <strong>NRP API key</strong> is required to use NRP/Nautilus models.
                </>
              )}
            </p>
            <p style={{ fontSize: 13 }}>
              {showKeyModal === 'fabric' ? (
                <>
                  To get your key, visit the <strong>FABRIC portal</strong> and generate an AI API key
                  from your account settings. Then enter it in <strong>LoomAI Settings &rarr; AI API Keys &rarr; FABRIC AI API Key</strong>.
                </>
              ) : (
                <>
                  Enter your NRP API key in <strong>LoomAI Settings &rarr; AI API Keys &rarr; NRP AI API Key</strong>.
                </>
              )}
            </p>
            <button className="ai-chat-key-modal-close" onClick={() => setShowKeyModal(null)}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
});
