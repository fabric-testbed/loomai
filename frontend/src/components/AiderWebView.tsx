'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import { startAiderWeb, stopAiderWeb, getAiderWebStatus, getAiModels } from '../api/client';
import ToolInstallOverlay from './ToolInstallOverlay';
import '../styles/terminal-companion.css';

function SidebarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <line x1="9" y1="3" x2="9" y2="21" />
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

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

interface Props {
  visible?: boolean;
}

export default function AiderWebView({ visible = true }: Props) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [status, setStatus] = useState<'loading' | 'running' | 'error'>('loading');
  const [port, setPort] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [installing, setInstalling] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Model picker
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [modelsLoading, setModelsLoading] = useState(false);
  const selectedModelRef = useRef('');

  useEffect(() => {
    setModelsLoading(true);
    getAiModels().then((data) => {
      setAvailableModels(data.models || []);
      const def = data.default || (data.models?.[0] ?? '');
      setSelectedModel(def);
      selectedModelRef.current = def;
    }).catch(() => {}).finally(() => setModelsLoading(false));
  }, []);

  const startAfterInstall = useCallback(async () => {
    setInstalling(false);
    setStatus('loading');
    try {
      const res = await startAiderWeb(selectedModelRef.current);
      if (res.status === 'running' && res.port) {
        setPort(res.port);
        setStatus('running');
      } else {
        setErrorMsg(res.error || 'Failed to start Aider');
        setStatus('error');
      }
    } catch (e: any) {
      setErrorMsg(e.message || 'Failed to start Aider');
      setStatus('error');
    }
  }, []);

  const launch = useCallback(async (model?: string) => {
    setStatus('loading');
    setErrorMsg('');
    try {
      const res = await startAiderWeb(model);
      if (res.install_required) {
        setInstalling(true);
        return;
      }
      if (res.status === 'running' && res.port) {
        setPort(res.port);
        setStatus('running');
      } else {
        setErrorMsg(res.error || 'Failed to start Aider');
        setStatus('error');
      }
    } catch (e: any) {
      setErrorMsg(e.message || 'Failed to start Aider');
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    getAiderWebStatus().then((res) => {
      if (res.status === 'running' && res.port) {
        setPort(res.port);
        setStatus('running');
      } else {
        launch(selectedModelRef.current);
      }
    }).catch(() => {
      launch(selectedModelRef.current);
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const restartSession = useCallback(async () => {
    setStatus('loading');
    try {
      await stopAiderWeb();
    } catch {}
    await launch(selectedModelRef.current);
  }, [launch]);

  const refreshIframe = useCallback(() => {
    if (iframeRef.current) {
      // eslint-disable-next-line no-self-assign
      iframeRef.current.src = iframeRef.current.src;
    }
  }, []);

  const basePath = (typeof window !== 'undefined' && window.__LOOMAI_BASE_PATH) || '';
  const iframeUrl = port ? (basePath ? `${basePath}/aider/` : `http://${window.location.hostname}:${port}`) : '';

  return (
    <div className="tc-layout">
      {installing && (
        <ToolInstallOverlay
          toolId="aider"
          onComplete={startAfterInstall}
          onError={(msg) => {
            setInstalling(false);
            setErrorMsg(msg);
            setStatus('error');
          }}
        />
      )}
      <div className={`tc-sidebar ${sidebarOpen ? '' : 'collapsed'}`}>
        <div className="tc-sidebar-header">
          <span className="tc-sidebar-icon aider">Ai</span>
          <span className="tc-sidebar-title">Aider</span>
          <button className="tc-sidebar-toggle" onClick={() => setSidebarOpen(false)} title="Hide sidebar">
            <SidebarIcon />
          </button>
        </div>
        <div className="tc-sidebar-section">
          <div className="tc-sidebar-branding">
            <div className="tc-sidebar-tagline">AI pair programming in your browser</div>
            <span className="tc-sidebar-badge free">Free &bull; FABRIC API Key Required</span>
          </div>
          <div className="tc-sidebar-desc">
            Edit files, generate scripts, and refactor code with AI assistance.
            Powered by <strong>FABRIC-hosted LLMs</strong> — free for FABRIC users with an API key.
            Get your key from the FABRIC portal, then add files with /add and Aider will apply changes directly.
          </div>
          <button className="tc-new-session-btn" onClick={restartSession} title="Restart Aider session">
            <PlusIcon />
            New Session
          </button>
          <div className="tc-sidebar-status">
            <span className={`tc-status-dot ${status === 'running' ? 'connected' : 'disconnected'}`} />
            {status === 'loading' ? 'Starting...' : status === 'running' ? 'Running' : 'Error'}
          </div>
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
                  {availableModels.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
                <div className="tc-model-hint">Change model and click &ldquo;New Session&rdquo; to apply</div>
              </>
            ) : (
              <span className="tc-model-loading">No models available</span>
            )}
          </div>
          <div className="tc-sidebar-tips">
            <strong>Tips</strong><br />
            Use /add to add files to the chat. /help for all commands. /drop to remove files.
          </div>
        </div>
      </div>
      <div className="tc-main">
        <div className="tc-main-header">
          {!sidebarOpen && (
            <button className="tc-sidebar-open-btn" onClick={() => setSidebarOpen(true)} title="Show sidebar">
              <SidebarIcon />
            </button>
          )}
          <span className="tc-header-title">Aider</span>
          <span className="tc-header-badge">Web</span>
          <button className="tc-popout-btn" onClick={() => window.open(iframeUrl || (basePath ? `${basePath}/aider/` : `http://${window.location.hostname}:9197`), '_blank')} title="Open in new tab">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
          </button>
          <button className="tc-refresh-btn" onClick={refreshIframe} title="Reload Aider web UI">
            <RefreshIcon />
          </button>
        </div>
        <div className="tc-terminal-wrapper">
          {status === 'loading' && (
            <div className="tc-loading">
              <div className="tc-loading-spinner" />
              <div className="tc-loading-text">Starting Aider...</div>
            </div>
          )}
          {status === 'error' && (
            <div className="tc-loading">
              <div className="tc-loading-text tc-loading-error">{errorMsg}</div>
              <button className="tc-new-session-btn" style={{ maxWidth: 200, marginTop: 12 }} onClick={restartSession}>
                Retry
              </button>
            </div>
          )}
          {status === 'running' && iframeUrl && (
            <iframe
              ref={iframeRef}
              src={iframeUrl}
              className="tc-opencode-iframe"
              title="Aider"
              allow="clipboard-read; clipboard-write"
            />
          )}
        </div>
      </div>
    </div>
  );
}
