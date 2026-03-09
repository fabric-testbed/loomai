'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import * as api from '../api/client';
import '../styles/jupyter-view.css';

interface JupyterLabViewProps {
  initialPath?: string;
  dark?: boolean;
}

export default function JupyterLabView({ initialPath, dark }: JupyterLabViewProps) {
  const [status, setStatus] = useState<'loading' | 'running' | 'error'>('loading');
  const [port, setPort] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState('');
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const launch = useCallback(async () => {
    setStatus('loading');
    setErrorMsg('');
    try {
      const res = await api.startJupyter();
      if (res.status === 'running' && res.port) {
        setPort(res.port);
        setStatus('running');
      } else {
        setErrorMsg(res.error || 'Failed to start JupyterLab');
        setStatus('error');
      }
    } catch (e: any) {
      setErrorMsg(e.message || 'Failed to start JupyterLab');
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    api.getJupyterStatus().then((res) => {
      if (res.status === 'running' && res.port) {
        setPort(res.port);
        setStatus('running');
      } else {
        launch();
      }
    }).catch(() => launch());
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync JupyterLab theme when dark mode or running status changes
  useEffect(() => {
    if (status === 'running' && dark !== undefined) {
      api.setJupyterTheme(dark ? 'dark' : 'light').catch(() => {});
    }
  }, [status, dark]);

  const refreshIframe = useCallback(() => {
    if (iframeRef.current) {
      // eslint-disable-next-line no-self-assign
      iframeRef.current.src = iframeRef.current.src;
    }
  }, []);

  const iframeUrl = port ? (initialPath || '/jupyter/') : '';

  return (
    <div className="jupyter-view">
      <div className="jupyter-toolbar">
        <span className="jupyter-toolbar-title">JupyterLab</span>
        {status === 'running' && (
          <>
            <button onClick={refreshIframe}>Refresh</button>
            <button className="jupyter-stop-btn" onClick={async () => {
              await api.stopJupyter().catch(() => {});
              setStatus('loading');
              setPort(null);
              launch();
            }}>Restart</button>
          </>
        )}
        <div className="jupyter-sep" />
        <span className="jupyter-status">
          {status === 'running' && <span className="jupyter-status-active">Running</span>}
          {status === 'loading' && <span className="jupyter-status-connecting">Starting...</span>}
          {status === 'error' && <span className="jupyter-status-error">Error</span>}
        </span>
      </div>

      {status === 'error' && errorMsg && (
        <div className="jupyter-error">
          {errorMsg}
          <button style={{ marginLeft: 12 }} onClick={launch}>Retry</button>
        </div>
      )}

      <div className="jupyter-iframe-wrap">
        {status === 'running' && iframeUrl ? (
          <iframe
            ref={iframeRef}
            src={iframeUrl}
            title="JupyterLab"
            allow="clipboard-read; clipboard-write"
          />
        ) : status === 'loading' ? (
          <div className="jupyter-placeholder">
            <div className="jupyter-spinner" />
            <div>Starting JupyterLab...</div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
