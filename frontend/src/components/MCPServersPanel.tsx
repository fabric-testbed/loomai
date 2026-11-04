'use client';
import { useCallback, useEffect, useState } from 'react';
import * as api from '../api/client';
import type { MCPServerInfo, MCPToolInfo } from '../api/client';

/** Chip label for how a server is reached. */
function transportLabel(srv: MCPServerInfo): string {
  return srv.transport === 'stdio' ? 'local stdio' : 'HTTPS';
}

function authLabel(srv: MCPServerInfo): string {
  return srv.auth === 'fabric_token' ? 'FABRIC token' : 'no auth';
}

interface StatusChip {
  text: string;
  tone: 'ok' | 'warn' | 'error';
}

function statusChip(srv: MCPServerInfo): StatusChip {
  const st = srv.status;
  if (!st) return { text: 'not probed', tone: 'warn' };
  if (!st.reachable) return { text: 'unreachable', tone: 'error' };
  if (st.local) return { text: 'local', tone: 'ok' };
  if (st.auth_warning) return { text: `${st.tool_count} tools · auth issue`, tone: 'warn' };
  const latency = st.latency_ms != null ? ` · ${Math.round(st.latency_ms)}ms` : '';
  return { text: `${st.tool_count} tools${latency}`, tone: 'ok' };
}

const TONE_COLORS: Record<StatusChip['tone'], string> = {
  ok: 'var(--fabric-success, #008e7a)',
  warn: 'var(--fabric-warning, #ff8542)',
  error: 'var(--fabric-danger, #b00020)',
};

const chipStyle: React.CSSProperties = {
  fontSize: 10,
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
  padding: '2px 6px',
  borderRadius: 3,
  border: '1px solid var(--fabric-border-solid, #d6e4ed)',
  color: 'var(--fabric-text-muted, #838385)',
  whiteSpace: 'nowrap',
};

export default function MCPServersPanel() {
  const [servers, setServers] = useState<MCPServerInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [tools, setTools] = useState<Record<string, MCPToolInfo[]>>({});
  const [probing, setProbing] = useState<string>('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.getMCPServers(true);
      setServers(res.servers || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const toggle = async (name: string) => {
    const next = new Set(expanded);
    if (next.has(name)) {
      next.delete(name);
      setExpanded(next);
      return;
    }
    next.add(name);
    setExpanded(next);
    if (tools[name]) return;
    try {
      const detail = await api.getMCPServer(name);
      setTools((prev) => ({ ...prev, [name]: detail.status?.tools || [] }));
    } catch {
      setTools((prev) => ({ ...prev, [name]: [] }));
    }
  };

  const probe = async (name: string) => {
    setProbing(name);
    try {
      const status = await api.probeMCPServer(name);
      setServers((prev) => prev.map((s) => (s.name === name ? { ...s, status } : s)));
      setTools((prev) => ({ ...prev, [name]: status.tools || [] }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setProbing('');
    }
  };

  return (
    <div className="configure-section" data-testid="configure-mcp">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h3>MCP Servers</h3>
        <button className="btn-sm" onClick={() => void load()} disabled={loading} data-testid="mcp-refresh">
          {loading ? 'Checking…' : 'Refresh'}
        </button>
      </div>
      <p style={{ fontSize: 12, color: 'var(--fabric-text-muted, #838385)', marginBottom: 12 }}>
        Model Context Protocol servers LoomAI and the in-container AI tools can call.
        Servers marked <strong>Assistant</strong> are also available to the LoomAI chat
        panel as tools; the rest are wired into the generated harness configs
        (<code>opencode.json</code>, <code>.mcp.json</code>).
      </p>

      {error && <div className="message error" style={{ marginBottom: 8 }}>{error}</div>}
      {loading && servers.length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--fabric-text-muted, #838385)' }}>Probing servers…</div>
      )}

      {servers.map((srv) => {
        const chip = statusChip(srv);
        const isOpen = expanded.has(srv.name);
        const list = tools[srv.name];
        return (
          <div
            key={srv.name}
            data-testid="mcp-server-card"
            data-server={srv.name}
            style={{
              border: '1px solid var(--fabric-border-solid, #d6e4ed)',
              borderRadius: 6,
              padding: 12,
              marginBottom: 10,
              background: 'var(--fabric-white, #fff)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <strong style={{ fontSize: 14 }}>{srv.label}</strong>
              <code style={{ fontSize: 11, color: 'var(--fabric-text-muted, #838385)' }}>{srv.name}</code>
              <span
                data-testid="mcp-status"
                style={{ ...chipStyle, color: TONE_COLORS[chip.tone], borderColor: TONE_COLORS[chip.tone] }}
              >
                {chip.text}
              </span>
              <span style={{ flex: 1 }} />
              {srv.transport === 'http' && (
                <button
                  className="btn-sm"
                  onClick={() => void probe(srv.name)}
                  disabled={probing === srv.name}
                  data-testid="mcp-probe"
                >
                  {probing === srv.name ? 'Probing…' : 'Probe'}
                </button>
              )}
            </div>

            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '8px 0' }}>
              <span style={chipStyle}>{transportLabel(srv)}</span>
              <span style={chipStyle}>{authLabel(srv)}</span>
              {srv.loomai && (
                <span style={{ ...chipStyle, color: 'var(--fabric-primary-dark, #1f6a8c)', borderColor: 'var(--fabric-primary, #5798bc)' }}>
                  Assistant
                </span>
              )}
              {srv.requires_staff && (
                <span style={{ ...chipStyle, color: 'var(--fabric-warning, #ff8542)', borderColor: 'var(--fabric-warning, #ff8542)' }}>
                  staff only
                </span>
              )}
              {srv.harnesses.map((h) => (
                <span key={h} style={chipStyle}>{h}</span>
              ))}
            </div>

            {srv.url && (
              <div style={{ fontSize: 11, fontFamily: 'monospace', wordBreak: 'break-all', marginBottom: 6 }}>
                {srv.url}
              </div>
            )}
            {srv.transport === 'stdio' && srv.command.length > 0 && (
              <div style={{ fontSize: 11, fontFamily: 'monospace', marginBottom: 6 }}>
                {srv.command.join(' ')}
              </div>
            )}

            <p style={{ fontSize: 12, margin: '0 0 6px' }}>{srv.description}</p>

            {srv.status?.error && (
              <div className="message error" style={{ fontSize: 11 }}>{srv.status.error}</div>
            )}
            {srv.status?.auth_warning && (
              <div
                data-testid="mcp-auth-warning"
                style={{
                  fontSize: 11,
                  padding: '6px 8px',
                  borderRadius: 4,
                  background: 'var(--state-configuring-bg, #fff3e0)',
                  color: 'var(--fabric-warning, #ff8542)',
                  marginBottom: 6,
                }}
              >
                Tool discovery succeeded, but authenticated calls failed: {srv.status.auth_warning}
              </div>
            )}

            {(srv.status?.tool_count ?? 0) > 0 && (
              <button
                className="btn-sm"
                onClick={() => void toggle(srv.name)}
                data-testid="mcp-toggle-tools"
              >
                {isOpen ? 'Hide' : 'Show'} {srv.status?.tool_count} tools
              </button>
            )}

            {isOpen && (
              <div style={{ marginTop: 8 }}>
                {!list && <div style={{ fontSize: 12, color: 'var(--fabric-text-muted, #838385)' }}>Loading tools…</div>}
                {list?.map((t) => (
                  <div key={t.name} style={{ padding: '4px 0', borderTop: '1px solid var(--fabric-border-solid, #d6e4ed)' }}>
                    <code style={{ fontSize: 11 }}>{t.name}</code>
                    <div style={{ fontSize: 11, color: 'var(--fabric-text-muted, #838385)' }}>
                      {t.description.split('\n')[0]}
                    </div>
                  </div>
                ))}
                {list && list.length === 0 && (
                  <div style={{ fontSize: 12, color: 'var(--fabric-text-muted, #838385)' }}>No tools reported.</div>
                )}
              </div>
            )}
          </div>
        );
      })}

      {!loading && servers.length === 0 && !error && (
        <div style={{ fontSize: 12, color: 'var(--fabric-text-muted, #838385)' }}>No MCP servers registered.</div>
      )}
    </div>
  );
}
