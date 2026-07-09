import { useCallback, useEffect, useMemo, useState } from 'react';
import dynamic from 'next/dynamic';
import * as api from '../api/client';
import type { SphereRealization, SphereGraph, SphereXdc } from '../types/sphere';
import CytoscapeGraph from './CytoscapeGraph';

// Leaflet touches `window` at import — load the map only in the browser.
const SphereMap = dynamic(() => import('./SphereMap'), { ssr: false });
// chart.js is client-only — load the usage charts in the browser.
const SphereUsage = dynamic(() => import('./SphereUsage'), { ssr: false });
const SphereFileBrowser = dynamic(() => import('./SphereFileBrowser'), { ssr: false });

interface SphereSelection { experiment: string; realization: string }

interface SphereViewProps {
  dark?: boolean;
  defaultProject?: string;
  subView: 'realizations' | 'topology' | 'storage' | 'inventory' | 'map' | 'notebook';
  refreshNonce: number;
  selected: SphereSelection | null;
  /** Select a realization (show its resources) without leaving the Realizations tab. */
  onSelect: (sel: SphereSelection) => void;
  /** Select a realization AND open its Topology view (clicking the name). */
  onOpenRealization?: (sel: SphereSelection) => void;
  /** Realizations changed (e.g. after bulk relinquish) — refresh ribbon/dropdown. */
  onChanged?: () => void;
  onError?: (msg: string) => void;
  /** Open an in-browser SSH terminal to a node through its XDC jump chain. */
  onOpenTerminal?: (n: { experiment: string; realization: string; node: string; xdc: string; project?: string }) => void;
  /** Report the clicked node/network element so the SPHERE editor can inspect it. */
  onElementSelect?: (data: Record<string, any> | null) => void;
  /** Report materialization status so the SPHERE editor can show it. */
  onMatStatus?: (status: string) => void;
  /** XDCs (with readiness) — managed in the editor, consumed here for Connect. */
  xdcs?: SphereXdc[];
  /** The XDC (bare name) selected in the editor, used as the Connect jump. */
  selectedXdc?: string;
}

/** XDC identifiers in gRPC are the bare name; the listing/fqdn may be the
 *  qualified ``<name>.<project>`` form — keep the bare name for API calls. */
const bareXdc = (name: string) => (name || '').split('.', 1)[0];

// An XDC's `materialization` ref is `<rid>.<eid>.<pid>` (or '' when unattached).
// Parse it into the realization it is connected to.
function parseMat(mat?: string): { rid: string; eid: string; pid: string; label: string } | null {
  const parts = (mat || '').split('.');
  if (parts.length < 2 || !parts[0] || !parts[1]) return null;
  return { rid: parts[0], eid: parts[1], pid: parts.slice(2).join('.'), label: `${parts[0]}.${parts[1]}` };
}

const resRec = (r: any) => (r?.resource || r || {});
const resCores = (r: any) => (resRec(r).procs || []).reduce((s: number, p: any) => s + (Number(p.cores) || 0), 0);
const resMemBytes = (r: any) => {
  const m = resRec(r).memory;
  const arr = Array.isArray(m) ? m : (m ? [m] : []);
  return arr.reduce((s: number, x: any) => s + (Number(x.capacity) || 0), 0);
};
const fmtBytes = (b: number) => {
  if (!b) return '—';
  const gb = b / (1024 ** 3);
  return gb >= 1024 ? `${(gb / 1024).toFixed(1)} TB` : `${gb.toFixed(0)} GB`;
};

/**
 * SPHERE (MergeTB) view. Two tabs (driven by the SPHERE bar in App):
 *  - Realizations: a table of realizations; selecting one shows its resources
 *    (nodes, IP addresses, facility), materialization status, XDC management,
 *    and a Connect button per node that opens an SSH terminal.
 *  - Topology: the selected realization's graph.
 *
 * Reaching a node requires an XDC (Experiment Data Conduit) — a Merge-hosted
 * jump container attached to the realization's materialization. This view lets
 * the user create/attach one and then SSH in, all without leaving LoomAI.
 */
export default function SphereView({ dark, defaultProject, subView, refreshNonce, selected, onSelect, onOpenRealization, onChanged, onError, onOpenTerminal, onElementSelect, onMatStatus, xdcs = [], selectedXdc = '' }: SphereViewProps) {
  const [realizations, setRealizations] = useState<SphereRealization[]>([]);
  const [loading, setLoading] = useState(false);
  const [graph, setGraph] = useState<SphereGraph | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [matStatus, setMatStatus] = useState<string>('');
  const [layout, setLayout] = useState('cose');
  const [inventory, setInventory] = useState<{ facilities: any[]; resources: any[]; pools: any[] } | null>(null);
  const [invLoading, setInvLoading] = useState(false);
  const [invFilter, setInvFilter] = useState('');

  // Prefer the selected realization's own project (pid) for realization-scoped
  // calls, so a wrong/typo'd default_project can't break graph/materialization/
  // connect. Fall back to the configured default.
  const project = useMemo(() => {
    if (selected) {
      const r = realizations.find(x => x.id === selected.realization && x.eid === selected.experiment);
      if (r?.pid) return r.pid;
    }
    return defaultProject || realizations[0]?.pid || '';
  }, [selected, realizations, defaultProject]);

  // Load inventory for the Inventory + Map tabs.
  useEffect(() => {
    if (subView !== 'inventory' && subView !== 'map') return;
    if (inventory) return;
    let cancelled = false;
    setInvLoading(true);
    api.getSphereInventory(defaultProject || undefined)
      .then(d => { if (!cancelled) setInventory(d); })
      .catch(e => { if (!cancelled) onError?.(`SPHERE: inventory load failed — ${e?.message || e}`); })
      .finally(() => { if (!cancelled) setInvLoading(false); });
    return () => { cancelled = true; };
  }, [subView, inventory, defaultProject]); // eslint-disable-line react-hooks/exhaustive-deps

  // Refresh inventory on the global refresh nonce.
  useEffect(() => { setInventory(null); }, [refreshNonce]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setRealizations(await api.listSphereRealizations({ summary: false, state: true }));
    } catch (e: any) {
      onError?.(`SPHERE: failed to list realizations — ${e?.message || e}`);
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { refresh(); }, [refresh, refreshNonce]);

  // Load graph + materialization for the selected realization.
  useEffect(() => {
    if (!selected) { setGraph(null); setMatStatus(''); return; }
    let cancelled = false;
    setGraphLoading(true);
    setGraph(null);
    api.getSphereRealizationGraph(selected.experiment, selected.realization, project || undefined)
      .then(g => { if (!cancelled) setGraph(g); })
      .catch(e => { if (!cancelled) onError?.(`SPHERE: graph load failed — ${e?.message || e}`); })
      .finally(() => { if (!cancelled) setGraphLoading(false); });
    api.getSphereMaterialization(selected.experiment, selected.realization, project || undefined)
      .then(m => { if (!cancelled) { const s = m?.taskSummary?.HighestStatus || 'not materialized'; setMatStatus(s); onMatStatus?.(s); } })
      .catch(() => { if (!cancelled) { setMatStatus('—'); onMatStatus?.('—'); } });
    return () => { cancelled = true; };
    // Only refetch when the realization/project changes — not on every render
    // (onError/onMatStatus are unstable inline props).
  }, [selected, project]); // eslint-disable-line react-hooks/exhaustive-deps

  // Multi-select + bulk relinquish (FABRIC-style).
  const [selKeys, setSelKeys] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const rkey = (r: SphereRealization) => `${r.id}.${r.eid}.${r.pid}`;
  const toggleKey = (k: string) => setSelKeys(prev => {
    const n = new Set(prev); n.has(k) ? n.delete(k) : n.add(k); return n;
  });
  const allSelected = realizations.length > 0 && realizations.every(r => selKeys.has(rkey(r)));
  const toggleAll = () => setSelKeys(allSelected ? new Set() : new Set(realizations.map(rkey)));
  const handleBulkRelinquish = useCallback(async () => {
    const targets = realizations.filter(r => selKeys.has(rkey(r)));
    if (!targets.length) return;
    if (typeof window !== 'undefined' && !window.confirm(
      `Relinquish ${targets.length} realization(s)? This releases their reserved resources.`)) return;
    setBulkBusy(true);
    for (const r of targets) {
      try { await api.relinquishSphere(r.eid, r.id, r.pid || defaultProject || undefined); }
      catch (e: any) { onError?.(`SPHERE: relinquish ${r.id}.${r.eid} failed — ${e?.message || e}`); }
    }
    setSelKeys(new Set());
    setBulkBusy(false);
    onChanged?.();
    refresh();
  }, [realizations, selKeys, defaultProject, onChanged, onError, refresh]);

  // The materialization ref this realization's XDC must be attached to.
  const realizationRef = useMemo(
    () => (selected ? `${selected.realization}.${selected.experiment}.${project}` : ''),
    [selected, project],
  );

  // XDCs attached to this realization come first; pick one as the default.
  const attachedXdcs = useMemo(
    () => xdcs.filter(x => (x.materialization || '') === realizationRef),
    [xdcs, realizationRef],
  );

  // Resource (node) rows derived from the graph's instance nodes.
  const resourceNodes = useMemo(
    () => (graph?.nodes || []).filter(n => n.data?.element_type === 'node').map(n => n.data),
    [graph],
  );

  const isSelected = (r: SphereRealization) =>
    selected && selected.experiment === r.eid && selected.realization === r.id;

  const selectedXdcAttached = attachedXdcs.some(x => bareXdc(x.name) === selectedXdc);
  const selectedXdcObj = useMemo(
    () => xdcs.find(x => bareXdc(x.name) === selectedXdc) || null,
    [xdcs, selectedXdc],
  );

  const [uploadMsg, setUploadMsg] = useState('');
  const [dropNode, setDropNode] = useState<string | null>(null);

  const handleDropOnNode = useCallback(async (node: string, files: FileList | null) => {
    setDropNode(null);
    if (!files || files.length === 0 || !selected) return;
    if (!selectedXdc || !selectedXdcAttached) {
      onError?.('SPHERE: attach an XDC to this realization first (Editor → XDC) before uploading.');
      return;
    }
    if (matStatus !== 'Success') { onError?.('SPHERE: realization is not fully materialized yet.'); return; }
    for (const file of Array.from(files)) {
      setUploadMsg(`Uploading ${file.name} → ${node}:~/ …`);
      try {
        await api.uploadSphereFile(file, selected.experiment, selected.realization, node, selectedXdc, project || undefined);
        setUploadMsg(`Uploaded ${file.name} → ${node}:~/${file.name}`);
      } catch (e: any) {
        setUploadMsg('');
        onError?.(`SPHERE: upload of ${file.name} to ${node} failed — ${e?.message || e}`);
      }
    }
  }, [selected, selectedXdc, selectedXdcAttached, matStatus, project, onError]);

  const handleConnect = useCallback((node: string) => {
    if (!selected || !selectedXdc) return;
    onOpenTerminal?.({
      experiment: selected.experiment, realization: selected.realization,
      node, xdc: selectedXdc, project: project || undefined,
    });
  }, [selected, selectedXdc, project, onOpenTerminal]);

  // Copy a packaged weave's notebook + scripts onto an XDC so they appear in its
  // JupyterLab (the XDC is a separate container from LoomAI storage).
  const [seedBusy, setSeedBusy] = useState('');
  const [seedMsg, setSeedMsg] = useState('');
  const seedWeaveToXdc = useCallback(async (xdcName: string, exp = '') => {
    try {
      const tmpls = await api.listTemplates();
      const weaves = tmpls.filter(t => t.format === 'sphere-experiment-v1');
      if (!weaves.length) {
        onError?.('No SPHERE weave packaged yet. Build one in Editor → Package first.');
        return;
      }
      // Prefer a weave whose dir name matches this experiment; else let the user pick.
      const pick = weaves.find(w => w.dir_name === `${exp}-weave` || w.dir_name === exp);
      let dir = pick?.dir_name;
      if (!dir) {
        const choice = typeof window !== 'undefined'
          ? window.prompt('Which weave to send to the XDC?\n' + weaves.map(w => '• ' + w.dir_name).join('\n'),
                          weaves[0].dir_name)
          : weaves[0].dir_name;
        if (!choice) return;
        dir = choice.trim();
      }
      setSeedBusy(xdcName);
      setSeedMsg('');
      const r = await api.seedSphereWeaveToXdc(xdcName, dir, project || undefined);
      setSeedMsg(`✓ Sent ${r.files} file(s) (${dir}) to XDC "${xdcName}" at ${r.dest}. Open/refresh its JupyterLab to see them.`);
    } catch (e: any) {
      onError?.(`Send weave to XDC failed — ${e?.message || e}`);
    } finally {
      setSeedBusy('');
    }
  }, [project, onError]);

  // ── Project Inventory tab ─────────────────────────────────────────────────
  if (subView === 'inventory') {
    const facilities = inventory?.facilities || [];
    const resources = inventory?.resources || [];
    const pools = inventory?.pools || [];
    const f = invFilter.trim().toLowerCase();
    const filteredResources = !f ? resources : resources.filter((r: any) => {
      const rr = resRec(r);
      return String(rr.id || '').toLowerCase().includes(f) || String(rr.facility || '').toLowerCase().includes(f);
    });
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, overflow: 'auto' }}>
        <div style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>Project Inventory {project && <span style={{ fontSize: 11, opacity: 0.7 }}>· {project}</span>}</div>
          <span style={{ fontSize: 11, opacity: 0.7 }}>{invLoading ? 'loading…' : `${facilities.length} facilities · ${resources.length} resources · ${pools.length} pools`}</span>
        </div>

        {resources.length > 0 && (
          <>
            <div style={{ padding: '0 12px 4px', fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', opacity: 0.7 }}>Resource Usage by Project</div>
            <SphereUsage resources={resources} dark={!!dark} />
          </>
        )}

        <div style={{ padding: '0 12px 8px', fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', opacity: 0.7 }}>Facilities</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr style={{ textAlign: 'left', borderBottom: '1px solid var(--fabric-border)' }}>
            <th style={{ padding: '6px 12px' }}>Facility</th><th style={{ padding: '6px 12px' }}>Address</th><th style={{ padding: '6px 12px' }}>Resources</th>
          </tr></thead>
          <tbody>
            {facilities.map((fac: any) => (
              <tr key={fac.name} style={{ borderBottom: '1px solid var(--fabric-border)' }}>
                <td style={{ padding: '6px 12px', fontWeight: 600 }}>{fac.name}</td>
                <td style={{ padding: '6px 12px', fontFamily: 'monospace', fontSize: 11 }}>{fac.address || '—'}</td>
                <td style={{ padding: '6px 12px' }}>{resources.filter((r: any) => resRec(r).facility === fac.name).length}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div style={{ padding: '14px 12px 8px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', opacity: 0.7 }}>Resources</span>
          <input value={invFilter} onChange={e => setInvFilter(e.target.value)} placeholder="filter by id or facility"
            style={{ fontSize: 11, padding: '3px 6px', border: '1px solid var(--fabric-border)', borderRadius: 4, flex: 1, maxWidth: 260 }} />
          <span style={{ fontSize: 11, opacity: 0.6 }}>{filteredResources.length} shown</span>
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr style={{ textAlign: 'left', borderBottom: '1px solid var(--fabric-border)' }}>
            <th style={{ padding: '6px 12px' }}>Resource</th><th style={{ padding: '6px 12px' }}>Facility</th>
            <th style={{ padding: '6px 12px' }}>Cores</th><th style={{ padding: '6px 12px' }}>Memory</th><th style={{ padding: '6px 12px' }}>State</th>
          </tr></thead>
          <tbody>
            {filteredResources.slice(0, 500).map((r: any, i: number) => {
              const rr = resRec(r);
              const allocated = Array.isArray(r.allocated) && r.allocated.length > 0;
              return (
                <tr key={(rr.id || i) + ':' + i} style={{ borderBottom: '1px solid var(--fabric-border)' }}>
                  <td style={{ padding: '6px 12px', fontWeight: 600 }}>{rr.id || '—'}</td>
                  <td style={{ padding: '6px 12px' }}>{rr.facility || '—'}</td>
                  <td style={{ padding: '6px 12px' }}>{resCores(r) || '—'}</td>
                  <td style={{ padding: '6px 12px' }}>{fmtBytes(resMemBytes(r))}</td>
                  <td style={{ padding: '6px 12px', color: allocated ? '#e2a23b' : '#008e7a' }}>{allocated ? 'in use' : 'free'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filteredResources.length > 500 && <div style={{ padding: '6px 12px', fontSize: 11, opacity: 0.6 }}>Showing first 500 — narrow the filter to see more.</div>}

        <div style={{ padding: '14px 12px 8px', fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', opacity: 0.7 }}>Allocation Pools</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, marginBottom: 16 }}>
          <thead><tr style={{ textAlign: 'left', borderBottom: '1px solid var(--fabric-border)' }}>
            <th style={{ padding: '6px 12px' }}>Pool</th><th style={{ padding: '6px 12px' }}>Projects</th><th style={{ padding: '6px 12px' }}>Facilities</th>
          </tr></thead>
          <tbody>
            {pools.map((p: any) => (
              <tr key={p.name} style={{ borderBottom: '1px solid var(--fabric-border)' }}>
                <td style={{ padding: '6px 12px', fontWeight: 600 }}>{p.name}</td>
                <td style={{ padding: '6px 12px' }}>{(p.projects || []).join(', ') || '—'}</td>
                <td style={{ padding: '6px 12px' }}>{Object.keys(p.facilities || {}).join(', ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // ── Map tab ───────────────────────────────────────────────────────────────
  if (subView === 'map') {
    const usedFacilities = new Set(resourceNodes.map((n: any) => n.facility).filter(Boolean));
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
        <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--fabric-border)', fontSize: 12 }}>
          <strong>SPHERE enclaves</strong>
          {selected && <span style={{ marginLeft: 12, opacity: 0.8 }}>realization {selected.realization}.{selected.experiment}</span>}
        </div>
        <div style={{ flex: 1, minHeight: 0 }}>
          <SphereMap inventory={inventory} usedFacilities={usedFacilities} dark={!!dark} />
        </div>
      </div>
    );
  }

  // ── Storage tab — node file manager over the XDC SSH chain ─────────────────
  if (subView === 'storage') {
    const nodeNames = resourceNodes.map((n: any) => n.name).filter(Boolean);
    const canAccess = !!selected && !!selectedXdc && selectedXdcAttached
      && selectedXdcObj?.ready !== false && matStatus === 'Success' && nodeNames.length > 0;
    const hint = !selected ? 'Select a realization first.'
      : !selectedXdc || !selectedXdcAttached ? 'Attach a ready XDC to this realization in the Editor → XDC tab.'
      : selectedXdcObj?.ready === false ? 'The XDC is still provisioning.'
      : matStatus !== 'Success' ? 'The realization is not fully materialized yet.'
      : 'No nodes available.';
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
        <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--fabric-border)', fontSize: 12 }}>
          <strong>Storage</strong>
          {selected && <span style={{ marginLeft: 12, opacity: 0.8 }}>{selected.realization}.{selected.experiment} · files on experiment nodes</span>}
        </div>
        <div style={{ flex: 1, minHeight: 0 }}>
          {selected ? (
            <SphereFileBrowser
              experiment={selected.experiment}
              realization={selected.realization}
              project={project || undefined}
              xdc={selectedXdc}
              nodes={nodeNames}
              canAccess={canAccess}
              accessHint={hint}
              onError={onError}
            />
          ) : (
            <div style={{ padding: 16, fontSize: 12, opacity: 0.7 }}>Select a realization to manage its node files.</div>
          )}
        </div>
      </div>
    );
  }

  // ── Notebook tab — launch the XDC's JupyterLab in a new tab ────────────────
  // SPHERE provides notebooks via each XDC's own JupyterLab (it carries the mrg
  // tooling + experiment context). Opening in a new tab is reliable; embedding
  // is blocked by the SPHERE site's frame policy.
  if (subView === 'notebook') {
    const launchable = xdcs.filter(x => x.url);
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, overflow: 'auto' }}>
        <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--fabric-border)', fontWeight: 600, fontSize: 13 }}>
          Notebook <span style={{ fontSize: 11, opacity: 0.7, fontWeight: 400 }}>· JupyterLab on your XDCs</span>
        </div>
        <div style={{ padding: 12 }}>
          <div style={{ fontSize: 12, opacity: 0.8, marginBottom: 12 }}>
            Each XDC runs its own JupyterLab (with the <code>mrg</code> CLI and access to the
            experiment it’s attached to). Open one in a new browser tab — you’re authenticated via your SPHERE session.
          </div>
          {launchable.length === 0 ? (
            <div style={{ fontSize: 12, opacity: 0.7 }}>
              No XDC available. Create and attach a shared XDC in the <strong>Editor → XDC</strong> tab,
              then launch its JupyterLab here.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 640 }}>
              {/* Attached XDCs first, so the ones tied to a realization are easy to find. */}
              {[...launchable].sort((a, b) => (parseMat(b.materialization) ? 1 : 0) - (parseMat(a.materialization) ? 1 : 0)).map(x => {
                const mat = parseMat(x.materialization);
                const ready = x.ready !== false;
                return (
                  <div key={x.name} style={{
                    display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px',
                    border: '1px solid var(--fabric-border)', borderRadius: 6,
                    background: mat ? 'rgba(0,142,122,0.06)' : undefined,
                  }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 12 }}>
                        {x.name}
                        {!ready && <span style={{ color: '#e2a23b', fontSize: 10 }}> ● provisioning</span>}
                      </div>
                      <div style={{ fontSize: 11, marginTop: 2 }}>
                        {mat
                          ? <span style={{ color: '#008e7a' }}>● connected to <strong>{mat.label}</strong></span>
                          : <span style={{ color: '#9a8', opacity: 0.85 }}>○ not attached to a realization</span>}
                      </div>
                      <div style={{ fontSize: 10, opacity: 0.55, fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{x.url}</div>
                    </div>
                    <button className="sphere-bar-btn" disabled={seedBusy === bareXdc(x.name)}
                      onClick={() => seedWeaveToXdc(bareXdc(x.name), mat?.eid || '')}
                      title="Copy a packaged weave's notebook + setup scripts into this XDC's JupyterLab"
                      style={{ color: 'var(--fabric-primary,#1f6a8c)', background: '#fff', borderColor: 'var(--fabric-border)', flexShrink: 0 }}>
                      {seedBusy === bareXdc(x.name) ? 'Sending…' : 'Send weave → XDC'}
                    </button>
                    <a className="sphere-bar-btn" href={x.url} target="_blank" rel="noopener noreferrer"
                      style={{ color: 'var(--fabric-primary,#1f6a8c)', borderColor: 'var(--fabric-border)', textDecoration: 'none', flexShrink: 0 }}>
                      Open JupyterLab ↗
                    </a>
                  </div>
                );
              })}
            </div>
          )}
          {seedMsg && (
            <div style={{
              marginTop: 12, maxWidth: 520, fontSize: 12, color: '#0a7d2c',
              background: 'rgba(0,142,122,0.10)', border: '1px solid rgba(0,142,122,0.35)',
              borderRadius: 6, padding: '8px 10px', display: 'flex', alignItems: 'flex-start', gap: 8,
            }}>
              <span style={{ flex: 1 }}>{seedMsg}</span>
              <button onClick={() => setSeedMsg('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', opacity: 0.6 }}>✕</button>
            </div>
          )}
          <div style={{ fontSize: 11, opacity: 0.7, marginTop: 12, maxWidth: 520 }}>
            <strong>Where are my notebook &amp; scripts?</strong> Packaging writes them to
            LoomAI storage. The XDC is a separate container — use <em>Send weave → XDC</em>
            above (or the Storage tab’s <em>XDC</em> target) to copy them into the XDC’s
            JupyterLab home.
          </div>
        </div>
      </div>
    );
  }

  // ── Topology tab ──────────────────────────────────────────────────────────
  if (subView === 'topology') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
        <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--fabric-border)', fontSize: 12 }}>
          {selected ? (
            <><strong>{selected.realization}.{selected.experiment}.{project}</strong>
              {matStatus && <span style={{ marginLeft: 12, opacity: 0.8 }}>materialization: {matStatus}</span>}</>
          ) : <span style={{ opacity: 0.7 }}>Select a realization in the Realizations tab to view its topology.</span>}
        </div>
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', height: '100%', minHeight: 0 }}>
          {graphLoading ? (
            <div style={{ padding: 16, fontSize: 12 }}>Loading topology…</div>
          ) : graph && graph.nodes.length > 0 ? (
            <CytoscapeGraph
              graph={null}
              chameleonGraph={graph}
              layout={layout}
              dark={!!dark}
              sliceData={null}
              preserveLayout
              onLayoutChange={setLayout}
              onNodeClick={(data) => onElementSelect?.(data)}
              onEdgeClick={() => {}}
              onBackgroundClick={() => onElementSelect?.(null)}
              onContextAction={(action) => {
                if (action.type === 'sphere-ssh' && action.nodeName) {
                  if (!selectedXdc || !selectedXdcAttached) {
                    onError?.('SPHERE: attach an XDC to this realization first (Realizations tab) before connecting.');
                  } else if (selectedXdcObj?.ready === false) {
                    onError?.('SPHERE: the XDC is still provisioning — wait until it is ready.');
                  } else if (matStatus !== 'Success') {
                    onError?.('SPHERE: realization is not fully materialized yet.');
                  } else {
                    handleConnect(action.nodeName);
                  }
                }
              }}
            />
          ) : (
            <div style={{ padding: 16, fontSize: 12, opacity: 0.7 }}>
              {selected ? 'No topology to display for this realization.' : 'No realization selected.'}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Realizations tab ──────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, overflow: 'auto' }}>
      <div style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ fontWeight: 600, fontSize: 13 }}>
          Realizations {project && <span style={{ fontSize: 11, opacity: 0.7 }}>· {project}</span>}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {selKeys.size > 0 && (
            <button className="sphere-bar-btn" style={{ color: 'var(--fabric-coral,#e25241)', borderColor: 'var(--fabric-border)' }}
              disabled={bulkBusy} onClick={handleBulkRelinquish}
              title="Relinquish the selected realizations (release their resources)">
              {bulkBusy ? 'Relinquishing…' : `Relinquish (${selKeys.size})`}
            </button>
          )}
          <span style={{ fontSize: 11, opacity: 0.7 }}>{loading ? 'loading…' : `${realizations.length} realization(s)`}</span>
        </div>
      </div>

      {realizations.length === 0 && !loading ? (
        <div style={{ padding: 16, fontSize: 12, opacity: 0.7 }}>
          No realizations. Create an experiment with <strong>+ New Experiment</strong>, then push a
          model and realize it via <code>loomai sphere realize &lt;experiment&gt; &lt;realization&gt;</code>.
        </div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--fabric-border)' }}>
              <th style={{ padding: '6px 12px', width: 28 }}>
                <input type="checkbox" checked={allSelected} onChange={toggleAll} title="Select all" />
              </th>
              <th style={{ padding: '6px 12px' }}>Realization</th>
              <th style={{ padding: '6px 12px' }}>Experiment</th>
              <th style={{ padding: '6px 12px' }}>Project</th>
              <th style={{ padding: '6px 12px' }}>State</th>
            </tr>
          </thead>
          <tbody>
            {realizations.map(r => {
              const k = rkey(r);
              const sel = isSelected(r);
              return (
                <tr
                  key={k}
                  onClick={() => onSelect({ experiment: r.eid, realization: r.id })}
                  style={{
                    cursor: 'pointer',
                    borderBottom: '1px solid var(--fabric-border)',
                    background: sel ? 'var(--fabric-primary, #5798bc)' : 'transparent',
                    color: sel ? '#fff' : 'inherit',
                  }}
                >
                  <td style={{ padding: '6px 12px' }} onClick={e => e.stopPropagation()}>
                    <input type="checkbox" checked={selKeys.has(k)} onChange={() => toggleKey(k)} />
                  </td>
                  <td style={{ padding: '6px 12px', fontWeight: 600 }}>
                    <a
                      role="button"
                      onClick={e => { e.stopPropagation(); onOpenRealization?.({ experiment: r.eid, realization: r.id }); }}
                      title="Open topology"
                      style={{ cursor: 'pointer', textDecoration: 'underline', color: sel ? '#fff' : 'var(--fabric-primary,#1f6a8c)' }}
                    >
                      {r.id}
                    </a>
                  </td>
                  <td style={{ padding: '6px 12px' }}>{r.eid}</td>
                  <td style={{ padding: '6px 12px' }}>{r.pid}</td>
                  <td style={{ padding: '6px 12px' }}>
                    {(() => {
                      const st = r.state || (r.complete ? 'complete' : 'pending');
                      const color = st === 'complete' ? '#008e7a' : st === 'failed' ? 'var(--fabric-coral,#e25241)' : '#e2a23b';
                      return <span style={{ color }} title={st === 'failed' ? (r.error || 'realization failed') : undefined}>
                        {st}{st === 'failed' && r.error ? ' ⚠' : ''}
                      </span>;
                    })()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {/* Resources of the selected realization */}
      {selected && (
        <div style={{ borderTop: '2px solid var(--fabric-border)', marginTop: 8 }}>
          <div style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 12 }}>
            <strong style={{ fontSize: 12 }}>Resources — {selected.realization}.{selected.experiment}</strong>
            <span style={{ fontSize: 11, opacity: 0.8 }}>materialization: {matStatus || '…'}</span>
          </div>
          {(() => {
            const sr = realizations.find(r => r.id === selected.realization && r.eid === selected.experiment);
            if (sr?.state === 'failed') return (
              <div style={{ margin: '0 12px 10px', padding: '8px 10px', borderRadius: 6, fontSize: 11,
                background: 'rgba(226,82,65,0.12)', border: '1px solid var(--fabric-coral,#e25241)', color: 'var(--fabric-coral,#e25241)' }}>
                <strong>Realization failed.</strong> {sr.error || 'See diagnostics.'}{' '}
                Relinquish it and re-realize (e.g. with an entitled facility), or fix the model.
              </div>
            );
            return null;
          })()}

          {/* XDC indicator — management lives in the editor's XDC tab. */}
          <div style={{ padding: '0 12px 10px', fontSize: 11, opacity: 0.85 }}>
            XDC: {selectedXdc
              ? <><code>{selectedXdc}</code>{selectedXdcAttached
                  ? <span style={{ color: '#008e7a' }}> ● attached</span>
                  : <span style={{ color: '#e2a23b' }}> (not attached — use the Editor’s XDC tab)</span>}
                {selectedXdcObj?.ready === false && <span style={{ color: '#e2a23b' }}> · provisioning</span>}</>
              : <span style={{ opacity: 0.7 }}>none — create/attach one in the Editor’s XDC tab</span>}
          </div>

          {graphLoading ? (
            <div style={{ padding: '0 12px 12px', fontSize: 12 }}>Loading resources…</div>
          ) : resourceNodes.length === 0 ? (
            <div style={{ padding: '0 12px 12px', fontSize: 12, opacity: 0.7 }}>
              No node resources found. The realization may not be materialized yet.
            </div>
          ) : (
            <>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--fabric-border)' }}>
                    <th style={{ padding: '6px 12px' }}>Node</th>
                    <th style={{ padding: '6px 12px' }}>Addresses</th>
                    <th style={{ padding: '6px 12px' }}>Facility</th>
                    <th style={{ padding: '6px 12px' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {resourceNodes.map((n: any) => {
                    const canConnect = !!onOpenTerminal && !!selectedXdc && selectedXdcAttached && matStatus === 'Success' && selectedXdcObj?.ready !== false;
                    const title = !selectedXdc ? 'Create and attach an XDC first'
                      : !selectedXdcAttached ? 'Attach the selected XDC to this realization first'
                      : selectedXdcObj?.ready === false ? 'XDC is still provisioning — wait until ready'
                      : matStatus !== 'Success' ? 'Realization is not fully materialized yet'
                      : `SSH to ${n.name} via XDC ${selectedXdc}`;
                    const canUpload = !!selectedXdc && selectedXdcAttached && matStatus === 'Success' && selectedXdcObj?.ready !== false;
                    return (
                      <tr key={n.id} onClick={() => onElementSelect?.(n)}
                        onDragOver={canUpload ? (e) => { e.preventDefault(); setDropNode(n.name); } : undefined}
                        onDragLeave={() => setDropNode(d => d === n.name ? null : d)}
                        onDrop={canUpload ? (e) => { e.preventDefault(); handleDropOnNode(n.name, e.dataTransfer?.files); } : undefined}
                        title={canUpload ? `Drop files to upload to ${n.name}:~/` : undefined}
                        style={{
                          borderBottom: '1px solid var(--fabric-border)', cursor: 'pointer',
                          outline: dropNode === n.name ? '2px dashed var(--fabric-primary,#1f6a8c)' : 'none',
                          background: dropNode === n.name ? 'rgba(87,152,188,0.12)' : 'transparent',
                        }}>
                        <td style={{ padding: '6px 12px', fontWeight: 600 }}>{n.name}</td>
                        <td style={{ padding: '6px 12px', fontFamily: 'monospace' }}>{(n.addresses || []).join(', ') || '—'}</td>
                        <td style={{ padding: '6px 12px' }}>{n.facility || '—'}</td>
                        <td style={{ padding: '6px 12px', textAlign: 'right' }}>
                          <button
                            className="sphere-bar-btn"
                            style={{ color: 'var(--fabric-primary,#1f6a8c)', borderColor: 'var(--fabric-border)' }}
                            disabled={!canConnect}
                            title={title}
                            onClick={(e) => { e.stopPropagation(); handleConnect(n.name); }}
                          >
                            Connect
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {uploadMsg && <div style={{ padding: '6px 12px', fontSize: 11, color: '#008e7a' }}>{uploadMsg}</div>}
              <div style={{ padding: '2px 12px 8px', fontSize: 11, opacity: 0.7 }}>
                Tip: drag a file onto a node row to upload it to that node’s home directory (via the attached XDC).
              </div>
              <div style={{ padding: '8px 12px', fontSize: 11, opacity: 0.8 }}>
                <strong>Connect</strong> opens an in-browser SSH session to the node through the
                selected XDC. Equivalent CLI: <code>mrg xdc ssh -x {(selectedXdc || 'xdc')}.{project} &lt;node&gt;</code>.
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
