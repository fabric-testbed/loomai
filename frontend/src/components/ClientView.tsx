'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import type { SliceSummary, SliceData } from '../types/fabric';
import * as api from '../api/client';
import '../styles/client-view.css';

export interface ClientTarget {
  sliceName: string;
  nodeName: string;
  port: number;
}

interface ClientViewProps {
  slices: SliceSummary[];
  selectedSliceName: string;
  sliceData: SliceData | null;
  clientTarget: ClientTarget | null;
  onTargetChange: (target: ClientTarget | null) => void;
}

export default function ClientView({ slices, selectedSliceName, sliceData, clientTarget, onTargetChange }: ClientViewProps) {
  const [sliceName, setSliceName] = useState(clientTarget?.sliceName || selectedSliceName || '');
  const [nodeName, setNodeName] = useState(clientTarget?.nodeName || '');
  const [port, setPort] = useState(clientTarget?.port || 3000);
  const [iframeSrc, setIframeSrc] = useState('');
  const [iframeDark, setIframeDark] = useState(false);
  const [tunnelStatus, setTunnelStatus] = useState<string>('');
  const [tunnelError, setTunnelError] = useState<string>('');
  const [hasTunnel, setHasTunnel] = useState(false);

  // Use refs for mutable state that shouldn't trigger re-renders / effect re-runs
  const tunnelIdRef = useRef<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Track whether we ourselves triggered the clientTarget change (to avoid re-connect loop)
  const selfTriggeredRef = useRef(false);

  const [localSliceData, setLocalSliceData] = useState<SliceData | null>(
    sliceName === selectedSliceName ? sliceData : null
  );

  // Cleanup on unmount only
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (tunnelIdRef.current) {
        api.closeTunnel(tunnelIdRef.current).catch(() => {});
      }
    };
  }, []);

  // When clientTarget changes externally (e.g. from context menu), auto-connect.
  // Skip when we ourselves set it via onTargetChange inside doConnect.
  useEffect(() => {
    if (selfTriggeredRef.current) {
      selfTriggeredRef.current = false;
      return;
    }
    if (clientTarget) {
      setSliceName(clientTarget.sliceName);
      setNodeName(clientTarget.nodeName);
      setPort(clientTarget.port);
      doConnect(clientTarget.sliceName, clientTarget.nodeName, clientTarget.port);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientTarget]);

  // Load slice data when slice selection changes
  useEffect(() => {
    if (sliceName === selectedSliceName && sliceData) {
      setLocalSliceData(sliceData);
      return;
    }
    if (!sliceName) {
      setLocalSliceData(null);
      return;
    }
    let cancelled = false;
    api.getSlice(sliceName).then((data) => {
      if (!cancelled) setLocalSliceData(data);
    }).catch(() => {
      if (!cancelled) setLocalSliceData(null);
    });
    return () => { cancelled = true; };
  }, [sliceName, selectedSliceName, sliceData]);

  // Filter nodes with management_ip
  const nodes = (localSliceData?.nodes ?? []).filter((n) => n.management_ip);

  // Auto-select first node if current nodeName not valid
  useEffect(() => {
    if (nodes.length > 0 && !nodes.find((n) => n.name === nodeName)) {
      setNodeName(nodes[0].name);
    }
  }, [nodes, nodeName]);

  // Core connect function — no dependencies on React state that changes frequently
  const doConnect = useCallback(async (sn: string, nn: string, p: number) => {
    // Close previous tunnel
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (tunnelIdRef.current) {
      api.closeTunnel(tunnelIdRef.current).catch(() => {});
      tunnelIdRef.current = null;
      setHasTunnel(false);
    }

    setIframeSrc('');
    setTunnelError('');
    setTunnelStatus('connecting');

    try {
      const info = await api.createTunnel(sn, nn, p);
      tunnelIdRef.current = info.id;
      setHasTunnel(true);

      if (info.status === 'active') {
        const src = `http://${window.location.hostname}:${info.local_port}/`;
        setIframeSrc(src);
        setTunnelStatus('active');
        selfTriggeredRef.current = true;
        onTargetChange({ sliceName: sn, nodeName: nn, port: p });
        return;
      }

      // Poll until active or error
      const createdId = info.id;
      const poll = setInterval(async () => {
        // If tunnel was replaced by a new connect call, stop polling
        if (tunnelIdRef.current !== createdId) {
          clearInterval(poll);
          if (pollRef.current === poll) pollRef.current = null;
          return;
        }
        try {
          const tunnels = await api.listTunnels();
          const t = tunnels.find((x) => x.id === createdId);
          if (!t) {
            clearInterval(poll);
            if (pollRef.current === poll) pollRef.current = null;
            // Only update UI if this is still the active tunnel
            if (tunnelIdRef.current === createdId) {
              setTunnelStatus('error');
              setTunnelError('Tunnel disappeared during setup');
              tunnelIdRef.current = null;
              setHasTunnel(false);
            }
            return;
          }
          if (t.status === 'active') {
            clearInterval(poll);
            if (pollRef.current === poll) pollRef.current = null;
            if (tunnelIdRef.current === createdId) {
              const src = `http://${window.location.hostname}:${t.local_port}/`;
              setIframeSrc(src);
              setTunnelStatus('active');
              selfTriggeredRef.current = true;
              onTargetChange({ sliceName: sn, nodeName: nn, port: p });
            }
          } else if (t.status === 'error') {
            clearInterval(poll);
            if (pollRef.current === poll) pollRef.current = null;
            if (tunnelIdRef.current === createdId) {
              setTunnelStatus('error');
              setTunnelError(t.error || 'Tunnel setup failed');
            }
          }
        } catch {
          // polling error — keep trying
        }
      }, 1500);
      pollRef.current = poll;
    } catch (e: any) {
      setTunnelStatus('error');
      setTunnelError(e.message || 'Failed to create tunnel');
    }
  }, [onTargetChange]);

  const handleConnect = useCallback(() => {
    if (!sliceName || !nodeName || !port) return;
    doConnect(sliceName, nodeName, port);
  }, [sliceName, nodeName, port, doConnect]);

  const handleDisconnect = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (tunnelIdRef.current) {
      api.closeTunnel(tunnelIdRef.current).catch(() => {});
      tunnelIdRef.current = null;
      setHasTunnel(false);
    }
    setIframeSrc('');
    setTunnelStatus('');
    setTunnelError('');
    onTargetChange(null);
  }, [onTargetChange]);

  return (
    <div className="client-view">
      <div className="client-toolbar">
        <label>Slice</label>
        <select value={sliceName} onChange={(e) => { setSliceName(e.target.value); setIframeSrc(''); }}>
          <option value="">-- select --</option>
          {slices.filter((s) => s.state === 'StableOK' || s.state === 'ModifyOK').map((s) => (
            <option key={s.name} value={s.name}>{s.name}</option>
          ))}
        </select>

        <div className="client-sep" />

        <label>Node</label>
        <select value={nodeName} onChange={(e) => { setNodeName(e.target.value); setIframeSrc(''); }}>
          {nodes.length === 0 && <option value="">-- no nodes --</option>}
          {nodes.map((n) => (
            <option key={n.name} value={n.name}>{n.name}</option>
          ))}
        </select>

        <div className="client-sep" />

        <label>Port</label>
        <input
          type="number"
          min={1}
          max={65535}
          value={port}
          onChange={(e) => setPort(parseInt(e.target.value) || 3000)}
        />

        <button onClick={handleConnect} disabled={tunnelStatus === 'connecting'}>
          {tunnelStatus === 'connecting' ? 'Connecting...' : 'Connect'}
        </button>

        {hasTunnel && (
          <button onClick={handleDisconnect} className="client-disconnect-btn">
            Disconnect
          </button>
        )}

        <div className="client-sep" />

        <label>Theme</label>
        <button
          onClick={() => setIframeDark((d) => !d)}
          style={{ minWidth: 56 }}
        >
          {iframeDark ? 'Dark' : 'Light'}
        </button>

        {tunnelStatus && (
          <>
            <div className="client-sep" />
            <span className={`client-status client-status-${tunnelStatus}`}>
              {tunnelStatus === 'connecting' ? 'SSH tunnel connecting...' :
               tunnelStatus === 'active' ? 'Tunnel active' :
               tunnelStatus === 'error' ? 'Tunnel error' : tunnelStatus}
            </span>
          </>
        )}

        {iframeSrc && (
          <>
            <div className="client-sep" />
            <span className="client-url">{iframeSrc}</span>
          </>
        )}
      </div>

      {tunnelError && (
        <div className="client-error">{tunnelError}</div>
      )}

      {iframeSrc ? (
        <div
          className="client-iframe-wrap"
          style={iframeDark ? { filter: 'invert(1) hue-rotate(180deg)' } : undefined}
        >
          <iframe src={iframeSrc} title="Client View" sandbox="allow-scripts allow-same-origin allow-forms allow-popups" />
        </div>
      ) : (
        <div className="client-placeholder">
          {tunnelStatus === 'connecting'
            ? 'Establishing SSH tunnel to VM...'
            : 'Select a slice, node, and port, then click Connect to view the web service.'}
        </div>
      )}
    </div>
  );
}
