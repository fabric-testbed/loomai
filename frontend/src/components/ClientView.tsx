'use client';
import InAppSelect from './InAppSelect';
import { useState, useEffect, useCallback, useRef } from 'react';
import type { SliceSummary, SliceData } from '../types/fabric';
import type { TunnelInfo } from '../api/client';
import * as api from '../api/client';
import '../styles/client-view.css';

export interface ClientTarget {
  sliceName: string;
  nodeName: string;
  port: number;
  protocol?: string;
}

interface ClientViewProps {
  slices: SliceSummary[];
  selectedSliceName: string;
  sliceData: SliceData | null;
  clientTarget: ClientTarget | null;
  onTargetChange: (target: ClientTarget | null) => void;
}

/** Build the URL a user can open in a browser tab for a given tunnel. */
function tunnelUrl(localPort: number): string {
  const bp = (typeof window !== 'undefined' && window.__LOOMAI_BASE_PATH) || '';
  return bp
    ? `${bp}/tunnel/${localPort}/`
    : `http://${window.location.hostname}:${localPort}/`;
}

export default function ClientView({ slices, selectedSliceName, sliceData, clientTarget, onTargetChange }: ClientViewProps) {
  // --- Create-bar state ---
  const [sliceName, setSliceName] = useState(clientTarget?.sliceName || selectedSliceName || '');
  const [nodeName, setNodeName] = useState(clientTarget?.nodeName || '');
  const [port, setPort] = useState(clientTarget?.port || 3000);
  const [protocol, setProtocol] = useState<string>(clientTarget?.protocol || 'http');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  // --- Tunnel list state ---
  const [tunnels, setTunnels] = useState<TunnelInfo[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Track whether we triggered the clientTarget change ourselves
  const selfTriggeredRef = useRef(false);

  // Slice data for node dropdown
  const [localSliceData, setLocalSliceData] = useState<SliceData | null>(
    sliceName === selectedSliceName ? sliceData : null
  );

  // --- Poll tunnel list ---
  const refreshTunnels = useCallback(async () => {
    try {
      const list = await api.listTunnels();
      setTunnels(list);
    } catch {
      // ignore polling errors
    }
  }, []);

  useEffect(() => {
    refreshTunnels();
    const iv = setInterval(refreshTunnels, 5000);
    pollRef.current = iv;
    return () => clearInterval(iv);
  }, [refreshTunnels]);

  // --- Auto-connect from context menu (clientTarget) ---
  useEffect(() => {
    if (selfTriggeredRef.current) {
      selfTriggeredRef.current = false;
      return;
    }
    if (clientTarget) {
      setSliceName(clientTarget.sliceName);
      setNodeName(clientTarget.nodeName);
      setPort(clientTarget.port);
      setProtocol(clientTarget.protocol || 'http');
      doConnect(clientTarget.sliceName, clientTarget.nodeName, clientTarget.port, clientTarget.protocol || 'http');
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientTarget]);

  // --- Load slice data for node dropdown ---
  useEffect(() => {
    if (sliceName === selectedSliceName && sliceData) {
      setLocalSliceData(sliceData);
      return;
    }
    if (!sliceName) { setLocalSliceData(null); return; }
    let cancelled = false;
    api.getSlice(sliceName).then((data) => {
      if (!cancelled) setLocalSliceData(data);
    }).catch(() => {
      if (!cancelled) setLocalSliceData(null);
    });
    return () => { cancelled = true; };
  }, [sliceName, selectedSliceName, sliceData]);

  const nodes = (localSliceData?.nodes ?? []).filter((n) => n.management_ip);

  // Auto-select first node when list changes
  useEffect(() => {
    if (nodes.length > 0 && !nodes.find((n) => n.name === nodeName)) {
      setNodeName(nodes[0].name);
    }
  }, [nodes, nodeName]);

  // --- Connect ---
  const doConnect = useCallback(async (sn: string, nn: string, p: number, proto: string) => {
    setCreating(true);
    setCreateError('');
    try {
      await api.createTunnel(sn, nn, p, proto);
      selfTriggeredRef.current = true;
      onTargetChange({ sliceName: sn, nodeName: nn, port: p, protocol: proto });
      // Immediately refresh tunnel list so the new entry shows up
      await refreshTunnels();
    } catch (e: any) {
      setCreateError(e.message || 'Failed to create tunnel');
    } finally {
      setCreating(false);
    }
  }, [onTargetChange, refreshTunnels]);

  const handleConnect = useCallback(() => {
    if (!sliceName || !nodeName || !port) return;
    doConnect(sliceName, nodeName, port, protocol);
  }, [sliceName, nodeName, port, protocol, doConnect]);

  // --- Stop a tunnel ---
  const handleStop = useCallback(async (tunnelId: string) => {
    try {
      await api.closeTunnel(tunnelId);
    } catch {
      // ignore
    }
    refreshTunnels();
  }, [refreshTunnels]);

  return (
    <div className="client-view">
      {/* Create bar */}
      <div className="client-toolbar">
        <label>Slice</label>
        <InAppSelect value={sliceName} onChange={(e) => setSliceName(e.target.value)}>
          <option value="">-- select --</option>
          {slices.filter((s) => s.state === 'StableOK' || s.state === 'ModifyOK').map((s) => (
            <option key={s.name} value={s.name}>{s.name}</option>
          ))}
        </InAppSelect>

        <div className="client-sep" />

        <label>Node</label>
        <InAppSelect value={nodeName} onChange={(e) => setNodeName(e.target.value)}>
          {nodes.length === 0 && <option value="">-- no nodes --</option>}
          {nodes.map((n) => (
            <option key={n.name} value={n.name}>{n.name}</option>
          ))}
        </InAppSelect>

        <div className="client-sep" />

        <label>Port</label>
        <input
          type="number"
          min={1}
          max={65535}
          value={port}
          onChange={(e) => setPort(parseInt(e.target.value) || 3000)}
        />

        <div className="client-sep" />

        <label>Protocol</label>
        <InAppSelect value={protocol} onChange={(e) => setProtocol(e.target.value)}>
          <option value="http">HTTP</option>
          <option value="https">HTTPS</option>
        </InAppSelect>

        <button onClick={handleConnect} disabled={creating || !sliceName || !nodeName}>
          {creating ? 'Connecting...' : 'Connect'}
        </button>
      </div>

      {createError && (
        <div className="client-error">{createError}</div>
      )}

      {/* Tunnel list */}
      {tunnels.length === 0 ? (
        <div className="client-placeholder">
          No active tunnels. Select a slice, node, port, and protocol, then click Connect.
        </div>
      ) : (
        <div className="tunnel-list">
          {tunnels.map((t) => (
            <div key={t.id} className={`tunnel-row tunnel-row-${t.status}`}>
              <div className="tunnel-row-info">
                <span className="tunnel-row-main">
                  <span className={`tunnel-status-dot tunnel-dot-${t.status}`} />
                  <strong>{t.node_name}</strong>
                  <span className="tunnel-detail">:{t.remote_port}</span>
                  <span className="tunnel-detail">{t.protocol.toUpperCase()}</span>
                  <span className="tunnel-detail">{t.slice_name}</span>
                </span>
                {t.status === 'active' && (
                  <span className="tunnel-row-url">{tunnelUrl(t.local_port)}</span>
                )}
                {t.status === 'error' && t.error && (
                  <span className="tunnel-row-error">{t.error}</span>
                )}
              </div>
              <div className="tunnel-row-actions">
                <span className={`tunnel-status-label tunnel-status-${t.status}`}>
                  {t.status === 'connecting' ? 'Connecting...' :
                   t.status === 'active' ? 'Active' :
                   t.status === 'error' ? 'Error' : t.status}
                </span>
                {t.status === 'active' && (
                  <button
                    className="tunnel-open-btn"
                    onClick={() => window.open(tunnelUrl(t.local_port), '_blank', 'noopener')}
                    title="Open in new browser tab"
                  >
                    Open &#8599;
                  </button>
                )}
                <button
                  className="tunnel-stop-btn"
                  onClick={() => handleStop(t.id)}
                >
                  Stop
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
