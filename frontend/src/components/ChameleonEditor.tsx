'use client';
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import CytoscapeGraph from './CytoscapeGraph';
import ChameleonNodeTypeComboBox from './editor/ChameleonNodeTypeComboBox';
import ChameleonImageComboBox from './editor/ChameleonImageComboBox';
import * as api from '../api/client';
import type { ChameleonSite, ChameleonImage, ChameleonDraft, ChameleonNodeTypeDetail, ChameleonNetwork } from '../types/chameleon';

// --- Floating IP helpers (supports old string[] and new {node_id, nic}[] formats) ---
type FipEntry = string | { node_id: string; nic: number };

function fipHasNode(fips: FipEntry[], nodeId: string): boolean {
  return fips.some(e => typeof e === 'string' ? e === nodeId : e.node_id === nodeId);
}

function fipGetNic(fips: FipEntry[], nodeId: string): number {
  const entry = fips.find(e => typeof e === 'string' ? e === nodeId : e.node_id === nodeId);
  if (!entry) return 0;
  return typeof entry === 'string' ? 0 : entry.nic;
}

function fipToEntries(fips: FipEntry[]): Array<{ node_id: string; nic: number }> {
  return fips.map(e => typeof e === 'string' ? { node_id: e, nic: 0 } : e);
}

function fipAdd(fips: FipEntry[], nodeId: string, nic = 0): Array<{ node_id: string; nic: number }> {
  const entries = fipToEntries(fips).filter(e => e.node_id !== nodeId);
  entries.push({ node_id: nodeId, nic });
  return entries;
}

function fipRemove(fips: FipEntry[], nodeId: string): Array<{ node_id: string; nic: number }> {
  return fipToEntries(fips).filter(e => e.node_id !== nodeId);
}

function fipSetNic(fips: FipEntry[], nodeId: string, nic: number): Array<{ node_id: string; nic: number }> {
  return fipToEntries(fips).map(e => e.node_id === nodeId ? { ...e, nic } : e);
}

// --- Boot Config Panel for deployed Chameleon nodes ---
function ChameleonBootConfigPanel({ sliceId, nodeName }: { sliceId: string; nodeName: string }) {
  const [uploads, setUploads] = useState<Array<{ id: string; source: string; dest: string; order: number }>>([]);
  const [commands, setCommands] = useState<Array<{ id: string; command: string; order: number }>>([]);
  const [newCmd, setNewCmd] = useState('');
  const [newSrc, setNewSrc] = useState('');
  const [newDest, setNewDest] = useState('');
  const [saving, setSaving] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [results, setResults] = useState<Array<{ command?: string; source?: string; dest?: string; type?: string; status: string; output?: string; message?: string }>>([]);

  useEffect(() => {
    api.getChameleonBootConfig(sliceId, nodeName).then(cfg => {
      setUploads(cfg.uploads || []);
      setCommands(cfg.commands || []);
    }).catch(() => {});
  }, [sliceId, nodeName]);

  const addUpload = () => {
    if (!newSrc.trim() || !newDest.trim()) return;
    setUploads(prev => [...prev, { id: `upl-${Date.now()}`, source: newSrc.trim(), dest: newDest.trim(), order: prev.length }]);
    setNewSrc('');
    setNewDest('');
  };

  const addCommand = () => {
    if (!newCmd.trim()) return;
    setCommands(prev => [...prev, { id: `cmd-${Date.now()}`, command: newCmd.trim(), order: prev.length }]);
    setNewCmd('');
  };

  const removeUpload = (id: string) => setUploads(prev => prev.filter(u => u.id !== id));
  const removeCommand = (id: string) => setCommands(prev => prev.filter(c => c.id !== id));

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.saveChameleonBootConfig(sliceId, nodeName, { uploads, commands, network: [] });
    } catch {}
    setSaving(false);
  };

  const handleExecute = async () => {
    setExecuting(true);
    setResults([]);
    try {
      await handleSave();
      const result = await api.executeChameleonBootConfig(sliceId, nodeName) as any;
      setResults(result.results || []);
    } catch (e: any) {
      setResults([{ command: '(all)', status: 'error', output: e.message }]);
    }
    setExecuting(false);
  };

  const hasContent = uploads.length > 0 || commands.length > 0;

  return (
    <div style={{ marginTop: 8, borderTop: '1px solid var(--fabric-border)', paddingTop: 8 }}>
      <div style={{ fontWeight: 600, fontSize: 11, marginBottom: 6 }}>Boot Config</div>

      {/* File Uploads */}
      <div style={{ fontSize: 10, color: 'var(--fabric-text-muted)', marginBottom: 2 }}>File Uploads</div>
      {uploads.map(u => (
        <div key={u.id} style={{ display: 'flex', gap: 4, marginBottom: 2, fontSize: 10 }}>
          <code style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={`${u.source} → ${u.dest}`}>{u.source} → {u.dest}</code>
          <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--fabric-coral)', fontSize: 12 }} onClick={() => removeUpload(u.id)}>×</button>
        </div>
      ))}
      <div style={{ display: 'flex', gap: 4, marginTop: 2 }}>
        <input type="text" value={newSrc} onChange={e => setNewSrc(e.target.value)} placeholder="Local path" style={{ flex: 1, fontSize: 10, padding: '2px 4px' }} />
        <input type="text" value={newDest} onChange={e => setNewDest(e.target.value)} placeholder="Remote path"
          onKeyDown={e => { if (e.key === 'Enter') addUpload(); }}
          style={{ flex: 1, fontSize: 10, padding: '2px 4px' }} />
        <button style={{ fontSize: 10, padding: '2px 6px' }} onClick={addUpload}>+</button>
      </div>

      {/* Commands */}
      <div style={{ fontSize: 10, color: 'var(--fabric-text-muted)', marginTop: 6, marginBottom: 2 }}>Commands</div>
      {commands.map(c => (
        <div key={c.id} style={{ display: 'flex', gap: 4, marginBottom: 2, fontSize: 10 }}>
          <code style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.command}</code>
          <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--fabric-coral)', fontSize: 12 }} onClick={() => removeCommand(c.id)}>×</button>
        </div>
      ))}
      <div style={{ display: 'flex', gap: 4, marginTop: 2 }}>
        <input type="text" value={newCmd} onChange={e => setNewCmd(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') addCommand(); }}
          placeholder="Add command..." style={{ flex: 1, fontSize: 10, padding: '2px 4px' }} />
        <button style={{ fontSize: 10, padding: '2px 6px' }} onClick={addCommand}>+</button>
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
        <button style={{ fontSize: 10, padding: '2px 8px' }} onClick={handleSave} disabled={saving}>{saving ? 'Saving...' : 'Save'}</button>
        <button style={{ fontSize: 10, padding: '2px 8px', color: '#39B54A', border: '1px solid #39B54A', background: 'none', cursor: 'pointer' }}
          onClick={handleExecute} disabled={executing || !hasContent}>{executing ? 'Running...' : 'Execute'}</button>
      </div>

      {/* Results */}
      {results.length > 0 && (
        <div style={{ marginTop: 6, fontSize: 10 }}>
          {results.map((r, i) => (
            <div key={i} style={{ marginBottom: 2, color: r.status === 'ok' ? 'var(--fabric-teal)' : 'var(--fabric-coral)' }}>
              {r.status === 'ok' ? '✓' : '✗'} {r.type === 'upload' ? `${r.source} → ${r.dest}` : r.command}{r.output ? `: ${r.output.slice(0, 100)}` : ''}{r.message ? `: ${r.message}` : ''}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Types ---

type EditorState = 'empty' | 'drafting' | 'deploying' | 'deployed';

interface ChameleonEditorProps {
  sites: ChameleonSite[];
  onError?: (msg: string) => void;
  onDeployed?: (leaseId: string) => void;
  /** When true, show only the graph (no side panel). Side panel editing handled externally. */
  graphOnly?: boolean;
  /** When true, show only the editor forms (no graph). For use in the side panel. */
  formsOnly?: boolean;
  /** External draft ID — when provided, load this draft instead of managing internal state. */
  draftId?: string;
  /** Called when draft is modified (node/network added/removed) to sync state back to parent. */
  onDraftUpdated?: (draft: ChameleonDraft) => void;
  /** External draft data — when changed, sync local state and refresh graph. */
  draftData?: ChameleonDraft | null;
  /** Version counter — increments on every draft mutation to force graph refresh. */
  draftVersion?: number;
  /** Context menu action handler — forwarded to CytoscapeGraph for right-click actions. */
  onContextAction?: (action: any) => void;
  /** Recipes for context menu matching. */
  recipes?: any[];
  /** When true, auto-refresh graph every 30s to pick up live instance state. */
  autoRefresh?: boolean;
}

// --- Helpers ---

function statusClass(status: string): string {
  const s = status.toUpperCase();
  if (s === 'ACTIVE' || s === 'DEPLOYED') return 'chi-status-active';
  if (s === 'PENDING' || s === 'DEPLOYING' || s === 'DRAFT') return 'chi-status-pending';
  if (s === 'ERROR') return 'chi-status-error';
  return '';
}

function stateLabel(state: EditorState): string {
  switch (state) {
    case 'empty': return 'No Draft';
    case 'drafting': return 'Draft';
    case 'deploying': return 'Deploying';
    case 'deployed': return 'Active';
    default: return state;
  }
}

// --- Component ---

export default function ChameleonEditor({ sites, onError, onDeployed, graphOnly, formsOnly, draftId: externalDraftId, onDraftUpdated, draftData: externalDraftData, draftVersion, onContextAction, recipes, autoRefresh }: ChameleonEditorProps) {
  // Core state
  const [state, setState] = useState<EditorState>('empty');
  const [draft, setDraft] = useState<ChameleonDraft | null>(null);
  const [graphData, setGraphData] = useState<{ nodes: any[]; edges: any[] } | null>(null);

  // Dark mode detection
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const check = () => setDark(document.documentElement.getAttribute('data-theme') === 'dark');
    check();
    const obs = new MutationObserver(check);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => obs.disconnect();
  }, []);

  // Draft creation fields
  const [newDraftName, setNewDraftName] = useState('my-experiment');
  const [newDraftSite, setNewDraftSite] = useState('');

  // Node form
  const [nodeName, setNodeName] = useState('');
  const [nodeSite, setNodeSite] = useState('');
  const [nodeType, setNodeType] = useState('');
  const [nodeImage, setNodeImage] = useState('');
  const [nodeCount, setNodeCount] = useState(1);
  const [addingNode, setAddingNode] = useState(false);

  // Network form
  const [netName, setNetName] = useState('');
  const [netConnected, setNetConnected] = useState<string[]>([]);
  const [addingNet, setAddingNet] = useState(false);

  // Existing networks (for attach)
  const [existingNetworks, setExistingNetworks] = useState<ChameleonNetwork[]>([]);
  const [selectedExistingNet, setSelectedExistingNet] = useState('');
  const [existingNetNodes, setExistingNetNodes] = useState<string[]>([]);

  // Deploy form
  const [showDeploy, setShowDeploy] = useState(false);
  const [leaseName, setLeaseName] = useState('');
  const [durationHours, setDurationHours] = useState(24);
  const [deploying, setDeploying] = useState(false);
  const [deployStatus, setDeployStatus] = useState('');
  const [confirmAction, setConfirmAction] = useState<{ title: string; message: string; onConfirm: () => void; danger?: boolean } | null>(null);

  // Site data (node types, images) — cached per site
  const [nodeTypes, setNodeTypes] = useState<ChameleonNodeTypeDetail[]>([]);
  const [allImages, setAllImages] = useState<ChameleonImage[]>([]);
  const [loadingData, setLoadingData] = useState(false);
  const siteDataCache = React.useRef<Record<string, { nodeTypes: ChameleonNodeTypeDetail[]; images: ChameleonImage[] }>>({});

  // Filter images by selected node type's architecture (e.g., ARM images only for ARM nodes)
  const selectedNodeTypeDetail = useMemo(() => nodeTypes.find(nt => nt.node_type === nodeType), [nodeTypes, nodeType]);
  // Reset image selection when node type changes and current image isn't in filtered list
  const images: ChameleonImage[] = useMemo(() => {
    if (!selectedNodeTypeDetail?.cpu_arch || !allImages.length) return allImages;
    const arch = selectedNodeTypeDetail.cpu_arch.toLowerCase();
    // If no images have architecture info, show all
    const imagesWithArch = allImages.filter(img => img.architecture);
    if (imagesWithArch.length === 0) return allImages;
    // Filter: show images matching the architecture, plus images with unknown architecture
    const isArm = arch.includes('arm') || arch.includes('aarch64');
    return allImages.filter(img => {
      if (!img.architecture) return true; // unknown arch — show it
      const imgArch = img.architecture.toLowerCase();
      if (isArm) return imgArch.includes('arm') || imgArch.includes('aarch64');
      return !imgArch.includes('arm') && !imgArch.includes('aarch64'); // x86 — exclude ARM
    });
  }, [allImages, selectedNodeTypeDetail]);

  // Side panel editor tab
  const [chiEditorTab, setChiEditorTab] = useState<'leases' | 'servers' | 'networks'>('servers');

  // Reservation management
  const [extendHoursMap, setExtendHoursMap] = useState<Record<string, number>>({});
  const [extendingLease, setExtendingLease] = useState('');
  const [deletingLease, setDeletingLease] = useState('');
  const [availableLeases, setAvailableLeases] = useState<any[]>([]);
  const [loadingLeases, setLoadingLeases] = useState(false);

  // Unaffiliated instances (Add Existing Server)
  const [unaffiliatedInstances, setUnaffiliatedInstances] = useState<any[]>([]);
  const [loadingUnaffiliated, setLoadingUnaffiliated] = useState(false);
  const [addingExistingServer, setAddingExistingServer] = useState(false);
  const [selectedUnaffiliated, setSelectedUnaffiliated] = useState('');

  // Auto-reset image when filtered images change and current selection is invalid
  useEffect(() => {
    if (images.length > 0 && nodeImage && !images.find(img => img.id === nodeImage || img.name === nodeImage)) {
      setNodeImage(images[0].id);
    }
  }, [images, nodeImage]);

  // Graph layout
  const [layout, setLayout] = useState('dagre');

  // Selected graph element
  const [selectedElement, setSelectedElement] = useState<Record<string, string> | null>(null);

  const configuredSites = useMemo(() => sites.filter(s => s.configured), [sites]);

  // Initialize default site
  useEffect(() => {
    if (!newDraftSite && configuredSites.length > 0) {
      setNewDraftSite(configuredSites[0].name);
    }
  }, [configuredSites, newDraftSite]);

  // Load external draft when draftId prop changes
  useEffect(() => {
    if (!externalDraftId) {
      // No external draft — reset to empty if we had one
      if (draft && state === 'drafting') {
        setDraft(null);
        setState('empty');
        setGraphData(null);
      }
      return;
    }
    // If already loaded this draft, skip
    if (draft?.id === externalDraftId) return;
    // Load the draft
    api.getChameleonDraft(externalDraftId).then(d => {
      setDraft(d);
      setState('drafting');
      // Load graph
      api.getChameleonDraftGraph(externalDraftId).then(g => setGraphData(g)).catch(() => setGraphData(null));
    }).catch(err => {
      onError?.(`Failed to load draft: ${err.message}`);
    });
  }, [externalDraftId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync external draft data changes — triggered by draftVersion counter
  // Every time the side panel adds/removes a node or network, draftVersion increments
  useEffect(() => {
    if (!externalDraftData || !externalDraftId) return;
    setDraft(externalDraftData);
    setState(externalDraftData.state === 'Active' ? 'deployed' : externalDraftData.state === 'Deploying' ? 'deploying' : 'drafting');
    // Immediately update graph from local data (instant visual feedback)
    buildLocalGraph(externalDraftData);
    // Then fetch enriched graph from backend (live status colors, IPs)
    api.getChameleonDraftGraph(externalDraftId).then(g => setGraphData(g)).catch(() => {});
  }, [draftVersion, externalDraftId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Derive sites from draft nodes (or fall back to legacy draft.site)
  const draftSites = useMemo(() => {
    if (!draft) return [];
    const fromNodes = draft.nodes.map(n => n.site).filter(Boolean);
    if (fromNodes.length > 0) return [...new Set(fromNodes)].sort();
    return draft.site ? [draft.site] : [];
  }, [draft]);

  // Initialize nodeSite to first configured site when entering draft mode
  useEffect(() => {
    if (!nodeSite && configuredSites.length > 0) setNodeSite(configuredSites[0].name);
  }, [nodeSite, configuredSites]);

  // Load node types and images when the per-node site changes (with caching)
  const effectiveSite = nodeSite || configuredSites[0]?.name || '';
  useEffect(() => {
    if (!effectiveSite) return;
    // Check cache first
    const cached = siteDataCache.current[effectiveSite];
    if (cached) {
      setNodeTypes(cached.nodeTypes);
      setAllImages(cached.images);
      if (cached.nodeTypes.length > 0) setNodeType(cached.nodeTypes[0].node_type);
      if (cached.images.length > 0) setNodeImage(cached.images[0].id);
      return;
    }
    setLoadingData(true);
    Promise.all([
      api.getChameleonNodeTypesDetail(effectiveSite).then(d => d.node_types || []).catch(() => []),
      api.getChameleonImages(effectiveSite).catch(() => []),
    ]).then(([nt, img]) => {
      siteDataCache.current[effectiveSite] = { nodeTypes: nt, images: img };
      setNodeTypes(nt);
      setAllImages(img);
      if (nt.length > 0) setNodeType(nt[0].node_type);
      if (img.length > 0) setNodeImage(img[0].id);
    }).finally(() => setLoadingData(false));
  }, [effectiveSite]);

  // Fetch existing networks from all sites in draft
  useEffect(() => {
    if (draftSites.length === 0) return;
    Promise.all(draftSites.map(s => api.listChameleonNetworks(s).catch(() => [] as ChameleonNetwork[])))
      .then(results => setExistingNetworks(results.flat()));
  }, [draftSites.join(',')]);

  // Fetch available leases when Leases tab is shown
  useEffect(() => {
    if (chiEditorTab !== 'leases' || !formsOnly || draftSites.length === 0) return;
    setLoadingLeases(true);
    Promise.all(draftSites.map(s => api.listChameleonLeases(s).catch(() => [] as any[])))
      .then(results => setAvailableLeases(results.flat()))
      .finally(() => setLoadingLeases(false));
  }, [chiEditorTab, formsOnly, draftSites.join(',')]);

  // Auto-generate node name
  useEffect(() => {
    if (draft && !nodeName) {
      const idx = (draft.nodes?.length || 0) + 1;
      setNodeName(`node${idx}`);
    }
  }, [draft, nodeName]);

  // Refresh graph data
  const refreshGraph = useCallback(async (draftId?: string) => {
    const id = draftId || draft?.id;
    if (!id) { setGraphData(null); return; }
    try {
      const g = await api.getChameleonDraftGraph(id);
      setGraphData(g);
    } catch {
      // If graph endpoint fails, build a simple graph from draft data
      if (draft) {
        buildLocalGraph(draft);
      }
    }
  }, [draft]);

  // Auto-refresh graph every 30s when enabled (picks up live instance state)
  useEffect(() => {
    if (!autoRefresh || !draft?.id) return;
    const interval = setInterval(() => refreshGraph(draft.id), 30000);
    return () => clearInterval(interval);
  }, [autoRefresh, draft?.id, refreshGraph]);

  // Build a client-side graph from draft data (fallback)
  const buildLocalGraph = useCallback((d: ChameleonDraft) => {
    const nodes: any[] = [];
    const edges: any[] = [];

    // One cluster per unique site
    const sites = [...new Set(d.nodes.map(n => n.site).filter(Boolean))];
    if (sites.length === 0 && d.site) sites.push(d.site); // legacy fallback
    sites.forEach(site => {
      nodes.push({
        data: { id: `site-${site}`, label: site },
        classes: 'chameleon-cluster',
      });
    });

    // Add nodes parented to their site
    (d.nodes || []).forEach(n => {
      const label = n.count > 1 ? `${n.name} (x${n.count})` : n.name;
      nodes.push({
        data: {
          id: `node-${n.id}`,
          label,
          parent: n.site ? `site-${n.site}` : undefined,
          bg_color: '#e8f5e9',
          bg_color_dark: '#1a3a30',
          border_color: '#66bb6a',
          border_color_dark: '#4caf50',
        },
        classes: 'chameleon-instance',
      });
    });

    // Add networks from legacy d.networks[] array
    (d.networks || []).forEach(net => {
      nodes.push({
        data: { id: `net-${net.id}`, label: net.name },
        classes: 'network-l2',
      });
      (net.connected_nodes || []).forEach(nodeId => {
        edges.push({
          data: {
            id: `edge-${net.id}-${nodeId}`,
            source: `node-${nodeId}`,
            target: `net-${net.id}`,
            label: '',
          },
          classes: 'edge-l2',
        });
      });
    });

    // Add per-node NIC components and interface-based network connections
    const seenNets = new Set<string>();
    const fabnetNodeIds: string[] = [];  // Track FABNetv4 network node IDs for internet cloud
    (d.nodes || []).forEach(n => {
      (n.interfaces || []).forEach((ifc, idx) => {
        const nicIdx = ifc.nic ?? idx;
        const nicId = `nic-${n.id}-${nicIdx}`;

        // NIC component badge
        nodes.push({
          data: {
            id: nicId,
            label: `nic-${nicIdx}`,
            parent_vm: `node-${n.id}`,
            element_type: 'component',
            name: `nic-${nicIdx}`,
            model: 'NIC',
            node_name: n.name,
          },
          classes: 'component component-nic',
        });

        // If NIC has a network assigned, add the network node + edge
        if (ifc.network?.id) {
          const netNodeId = `ifcnet-${ifc.network.id}`;
          const isFabNet = ifc.network.name?.toLowerCase().includes('fabnet');
          if (!seenNets.has(netNodeId)) {
            seenNets.add(netNodeId);
            nodes.push({
              data: { id: netNodeId, label: ifc.network.name, element_type: 'network', name: ifc.network.name },
              classes: isFabNet ? 'network-l3 chameleon-draft-net' : 'network-l2 chameleon-draft-net',
            });
            if (isFabNet) fabnetNodeIds.push(netNodeId);
          }
          edges.push({
            data: { id: `edge-${nicId}-${ifc.network.id}`, source: nicId, target: netNodeId },
            classes: isFabNet ? 'edge-l3' : 'edge-l2',
          });
        }
      });
    });

    // Add FABRIC Internet cloud node if any FABNetv4 networks exist
    if (fabnetNodeIds.length > 0) {
      const internetId = 'fabnet-internet-v4';
      nodes.push({
        data: { id: internetId, label: '\u2601\nFABRIC Internet\n(FABNetv4)', element_type: 'fabnet-internet' },
        classes: 'fabnet-internet',
      });
      fabnetNodeIds.forEach(netId => {
        edges.push({
          data: { id: `edge-fabnet-${netId}`, source: netId, target: internetId, label: '' },
          classes: 'edge-fabnet-internet',
        });
      });
    }

    setGraphData({ nodes, edges });
  }, []);

  // --- Handlers ---

  const handleCreateDraft = useCallback(async () => {
    if (!newDraftName.trim()) return;
    try {
      const d = await api.createChameleonDraft({ name: newDraftName.trim() });
      setDraft(d);
      setState('drafting');
      setNodeName('node1');
      setNetName('');
      setNetConnected([]);
      setLeaseName(d.name);
      refreshGraph(d.id);
    } catch (e: any) {
      onError?.(e.message || 'Failed to create draft');
    }
  }, [newDraftName, refreshGraph, onError]);

  const handleDeleteDraft = useCallback(() => {
    if (!draft) return;
    setConfirmAction({
      title: 'Discard Draft',
      message: `Discard draft "${draft.name}"? This only removes the local draft.`,
      danger: true,
      onConfirm: async () => {
        try {
          await api.deleteChameleonDraft(draft.id);
        } catch {
          // Ignore — draft may not exist on server
        }
        setDraft(null);
        setGraphData(null);
        setState('empty');
        setNodeName('');
        setNetName('');
        setNetConnected([]);
        setShowDeploy(false);
        setDeployStatus('');
      },
    });
  }, [draft]);

  const handleAddNode = useCallback(async () => {
    if (!draft || !nodeType) return;
    const effectiveName = nodeName.trim() || `node-${draft.nodes.length + 1}`;
    setAddingNode(true);
    try {
      const updated = await api.addChameleonDraftNode(draft.id, {
        name: effectiveName,
        node_type: nodeType,
        image: nodeImage || 'CC-Ubuntu22.04',
        count: nodeCount,
        site: nodeSite || effectiveSite,
      });
      setDraft(updated);
      onDraftUpdated?.(updated);
      // Immediately update graph from local data (instant feedback)
      buildLocalGraph(updated);
      // Also fetch enriched graph from backend (live status, proper styling)
      refreshGraph(draft.id);
      // Auto-generate next name
      const idx = (updated.nodes?.length || 0) + 1;
      setNodeName(`node${idx}`);
      setNodeCount(1);
      // Auto-assign floating IP to new node (best-effort)
      const newNode = updated.nodes[updated.nodes.length - 1];
      if (newNode) {
        try {
          const withFip = await api.setDraftFloatingIps(updated.id, fipAdd(updated.floating_ips || [], newNode.id, 0));
          setDraft(withFip);
          onDraftUpdated?.(withFip);
        } catch { /* fall through — node added without FIP */ }
      }
    } catch (e: any) {
      onError?.(e.message || 'Failed to add node');
    } finally {
      setAddingNode(false);
    }
  }, [draft, nodeName, nodeType, nodeImage, nodeCount, nodeSite, effectiveSite, refreshGraph, onError]);

  const handleRemoveNode = useCallback(async (nodeId: string) => {
    if (!draft) return;
    try {
      const updated = await api.removeChameleonDraftNode(draft.id, nodeId);
      setDraft(updated);
      onDraftUpdated?.(updated);
      buildLocalGraph(updated);
      refreshGraph(draft.id);
    } catch (e: any) {
      onError?.(e.message || 'Failed to remove node');
    }
  }, [draft, refreshGraph, onError]);

  const handleAddNetwork = useCallback(async () => {
    if (!draft || !netName.trim()) return;
    setAddingNet(true);
    try {
      const updated = await api.addChameleonDraftNetwork(draft.id, {
        name: netName.trim(),
        connected_nodes: netConnected,
      });
      setDraft(updated);
      onDraftUpdated?.(updated);
      buildLocalGraph(updated);
      refreshGraph(draft.id);
      setNetName('');
      setNetConnected([]);
    } catch (e: any) {
      onError?.(e.message || 'Failed to add network');
    } finally {
      setAddingNet(false);
    }
  }, [draft, netName, netConnected, refreshGraph, onError]);

  const handleRemoveNetwork = useCallback(async (networkId: string) => {
    if (!draft) return;
    try {
      const updated = await api.removeChameleonDraftNetwork(draft.id, networkId);
      setDraft(updated);
      onDraftUpdated?.(updated);
      buildLocalGraph(updated);
      refreshGraph(draft.id);
    } catch (e: any) {
      onError?.(e.message || 'Failed to remove network');
    }
  }, [draft, refreshGraph, onError]);

  const handleToggleNetNode = useCallback((nodeId: string) => {
    setNetConnected(prev =>
      prev.includes(nodeId) ? prev.filter(n => n !== nodeId) : [...prev, nodeId]
    );
  }, []);

  const handleDeploy = useCallback(async () => {
    if (!draft) return;
    setDeploying(true);
    setDeployStatus('Creating lease...');
    setState('deploying');
    try {
      const result = await api.deployChameleonDraft(draft.id, {
        lease_name: leaseName || draft.name,
        duration_hours: durationHours,
      });
      const leaseCount = result.leases?.length || 0;
      const firstLease = result.leases?.[0];
      setDeployStatus(`${leaseCount} lease${leaseCount !== 1 ? 's' : ''} created${firstLease ? ` (${firstLease.status})` : ''}`);
      setState('deployed');
      onDeployed?.(firstLease?.lease_id || '');
    } catch (e: any) {
      setDeployStatus(`Deployment failed: ${e.message}`);
      setState('drafting');
      onError?.(e.message || 'Deployment failed');
    } finally {
      setDeploying(false);
    }
  }, [draft, leaseName, durationHours, onDeployed, onError]);

  // --- Render ---

  // When graphOnly, render just the graph (full width, no side panel)
  if (graphOnly) {
    return (
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', height: '100%', minHeight: 0 }}>
        {graphData && (graphData.nodes.length > 0 || graphData.edges.length > 0) ? (
          <CytoscapeGraph
            graph={null}
            layout={layout}
            dark={dark}
            sliceData={null}
            chameleonGraph={graphData}
            recipes={recipes}
            preserveLayout
            onLayoutChange={setLayout}
            onNodeClick={(data) => setSelectedElement(data)}
            onEdgeClick={() => {}}
            onBackgroundClick={() => setSelectedElement(null)}
            onContextAction={onContextAction || (() => {})}
          />
        ) : (
          <div className="chi-editor-empty-graph" style={{ flex: 1 }}>
            <div className="chi-editor-empty-icon">
              <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
                <rect x="8" y="8" width="20" height="16" rx="3" stroke={dark ? '#5cc96a' : '#39B54A'} strokeWidth="2" fill="none" />
                <rect x="36" y="8" width="20" height="16" rx="3" stroke={dark ? '#5cc96a' : '#39B54A'} strokeWidth="2" fill="none" />
                <rect x="22" y="40" width="20" height="16" rx="3" stroke={dark ? '#5cc96a' : '#39B54A'} strokeWidth="2" fill="none" />
                <line x1="18" y1="24" x2="32" y2="40" stroke={dark ? '#5cc96a66' : '#39B54A66'} strokeWidth="1.5" />
                <line x1="46" y1="24" x2="32" y2="40" stroke={dark ? '#5cc96a66' : '#39B54A66'} strokeWidth="1.5" />
              </svg>
            </div>
            <div className="chi-editor-empty-text">
              {state === 'empty' ? 'Create a draft to start building' : 'Add nodes and networks to see topology'}
            </div>
          </div>
        )}
      </div>
    );
  }

  // When formsOnly, render tabbed editor (like FABRIC's Slice/Slivers pattern).
  if (formsOnly) {
    return (
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {(!draft || state === 'empty') ? (
          <div style={{ padding: 16, textAlign: 'center', color: 'var(--fabric-text-muted)', fontSize: 12 }}>
            Select or create a draft from the Chameleon bar to start editing.
          </div>
        ) : (
          <>
            <div className="editor-top-tabs">
              <button className={chiEditorTab === 'leases' ? 'active chameleon-tab-active' : ''} onClick={() => setChiEditorTab('leases')}>Leases</button>
              <button className={chiEditorTab === 'servers' ? 'active chameleon-tab-active' : ''} onClick={() => setChiEditorTab('servers')}>Servers</button>
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: 8 }}>
              {chiEditorTab === 'leases' && (
                <div>
                  {/* Slice summary */}
                  <h4 style={{ margin: '0 0 8px', fontSize: 13 }}>{draft.name}</h4>
                  <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
                    <div><strong>State:</strong> {draft.state || 'Draft'}</div>
                    <div><strong>Servers:</strong> {draft.nodes.length} planned{draft.resources?.filter(r => r.type === 'instance').length ? `, ${draft.resources.filter(r => r.type === 'instance').length} deployed` : ''}</div>
                    {draftSites.length > 0 && <div><strong>Sites:</strong> {draftSites.join(', ')}</div>}
                  </div>

                  {/* Pre-submit configuration */}
                  {draft.state === 'Draft' && draft.nodes.length > 0 && (
                    <div style={{ borderTop: '1px solid var(--fabric-border)', paddingTop: 8, marginBottom: 8 }}>
                      <h5 style={{ fontSize: 11, fontWeight: 700, margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--fabric-text-muted)' }}>Reservation</h5>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                        <label style={{ fontSize: 11, fontWeight: 500, minWidth: 60 }}>Duration:</label>
                        <input
                          type="number"
                          className="chi-form-input"
                          min={1}
                          max={168}
                          value={durationHours}
                          onChange={e => setDurationHours(Number(e.target.value))}
                          style={{ width: 60, fontSize: 11 }}
                        />
                        <span style={{ fontSize: 11, color: 'var(--fabric-text-muted)' }}>hours</span>
                      </div>
                      <div style={{ fontSize: 10, color: 'var(--fabric-text-muted)', marginBottom: 4 }}>
                        {draft.nodes.length} server{draft.nodes.length !== 1 ? 's' : ''} across {draftSites.length} site{draftSites.length !== 1 ? 's' : ''} will be reserved.
                      </div>
                      <div style={{ fontSize: 10, color: 'var(--fabric-text-muted)' }}>
                        Click <strong>Submit</strong> in the toolbar to create the reservation and deploy.
                      </div>
                    </div>
                  )}

                  {/* Existing lease management */}
                  {(draft.resources || []).filter(r => r.type === 'lease').length === 0 ? (
                    draft.state !== 'Draft' ? (
                      <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', padding: '8px 0', borderTop: '1px solid var(--fabric-border)' }}>
                        No active leases.
                      </div>
                    ) : null
                  ) : (
                    <>
                      <div style={{ borderTop: '1px solid var(--fabric-border)', paddingTop: 8 }}>
                        <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 6px' }}>
                          Leases ({(draft.resources || []).filter(r => r.type === 'lease').length})
                        </h5>
                      </div>
                      {(draft.resources || []).filter(r => r.type === 'lease').map(lease => (
                        <div key={lease.resource_id} style={{ border: '1px solid var(--fabric-border)', borderRadius: 6, padding: 8, marginBottom: 8 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                            <span style={{ fontWeight: 600, fontSize: 12 }}>{lease.name}</span>
                            <span className={`chi-status ${statusClass(lease.status || 'UNKNOWN')}`} style={{ fontSize: 9 }}>
                              {lease.status || 'UNKNOWN'}
                            </span>
                          </div>
                          <div style={{ fontSize: 10, color: 'var(--fabric-text-muted)', marginBottom: 6 }}>
                            <div>Site: {lease.site}</div>
                            <div>ID: {lease.id.slice(0, 12)}...</div>
                          </div>
                          <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 4 }}>
                            <input
                              type="number"
                              className="chi-form-input"
                              min={1}
                              max={168}
                              value={extendHoursMap[lease.resource_id] ?? 24}
                              onChange={e => setExtendHoursMap(prev => ({ ...prev, [lease.resource_id]: Number(e.target.value) }))}
                              style={{ width: 60, fontSize: 10 }}
                            />
                            <span style={{ fontSize: 10 }}>hours</span>
                            <button
                              className="chi-editor-deploy-btn"
                              style={{ fontSize: 10, padding: '2px 8px' }}
                              disabled={extendingLease === lease.resource_id}
                              onClick={async () => {
                                setExtendingLease(lease.resource_id);
                                try {
                                  await api.extendChameleonLease(lease.id, lease.site, extendHoursMap[lease.resource_id] ?? 24);
                                } catch (e: any) {
                                  onError?.(e.message || 'Failed to extend lease');
                                } finally {
                                  setExtendingLease('');
                                }
                              }}
                            >
                              {extendingLease === lease.resource_id ? 'Extending...' : 'Extend'}
                            </button>
                          </div>
                          <button
                            className="chi-action-btn chi-action-btn-danger"
                            style={{ fontSize: 10, width: '100%' }}
                            disabled={deletingLease === lease.resource_id}
                            onClick={async () => {
                              setDeletingLease(lease.resource_id);
                              try {
                                await api.deleteChameleonLease(lease.id, lease.site);
                                const updated = await api.removeChameleonSliceResource(draft.id, lease.resource_id);
                                setDraft(updated);
                                onDraftUpdated?.(updated);
                              } catch (e: any) {
                                onError?.(e.message || 'Failed to delete lease');
                              } finally {
                                setDeletingLease('');
                              }
                            }}
                          >
                            {deletingLease === lease.resource_id ? 'Deleting...' : 'Delete Lease'}
                          </button>
                        </div>
                      ))}
                    </>
                  )}

                  {/* Available leases checklist */}
                  <div style={{ borderTop: '1px solid var(--fabric-border)', paddingTop: 8, marginTop: 8 }}>
                    <h5 style={{ fontSize: 11, fontWeight: 700, margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--fabric-text-muted)' }}>
                      Available Leases {loadingLeases && '...'}
                    </h5>
                    {availableLeases.length === 0 && !loadingLeases ? (
                      <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', padding: '4px 0' }}>
                        No leases found at {draftSites.join(', ') || 'any site'}.
                      </div>
                    ) : (
                      availableLeases.map(lease => {
                        const sliceLeaseIds = new Set((draft.resources || []).filter(r => r.type === 'lease').map(r => r.id));
                        const isIncluded = sliceLeaseIds.has(lease.id);
                        return (
                          <label key={lease.id} style={{
                            display: 'flex', alignItems: 'flex-start', gap: 8, padding: '5px 2px',
                            cursor: 'pointer', fontSize: 11, borderBottom: '1px solid var(--fabric-border)',
                          }}>
                            <input
                              type="checkbox"
                              checked={isIncluded}
                              style={{ marginTop: 2, accentColor: '#39B54A' }}
                              onChange={async (e) => {
                                if (!draft) return;
                                try {
                                  let updated;
                                  if (e.target.checked) {
                                    updated = await api.addChameleonSliceResource(draft.id, {
                                      type: 'lease',
                                      id: lease.id,
                                      name: lease.name,
                                      site: lease.site || '',
                                      status: lease.status,
                                    });
                                  } else {
                                    const res = (draft.resources || []).find(r => r.type === 'lease' && r.id === lease.id);
                                    if (res) {
                                      updated = await api.removeChameleonSliceResource(draft.id, res.resource_id);
                                    }
                                  }
                                  if (updated) {
                                    setDraft(updated);
                                    onDraftUpdated?.(updated);
                                    refreshGraph(draft.id);
                                  }
                                } catch (err: any) {
                                  onError?.(err?.message || 'Failed to update lease membership');
                                }
                              }}
                            />
                            <div style={{ flex: 1 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                <span style={{ fontWeight: 600 }}>{lease.name}</span>
                                <span className={`chi-status ${statusClass(lease.status || 'UNKNOWN')}`} style={{ fontSize: 9 }}>
                                  {lease.status || 'UNKNOWN'}
                                </span>
                              </div>
                              <div style={{ fontSize: 10, color: 'var(--fabric-text-muted)' }}>
                                {lease.site && <span>@ {lease.site}</span>}
                                {lease.reservations?.[0] && (
                                  <span style={{ marginLeft: 6 }}>
                                    {lease.reservations[0].resource_type === 'physical:host' ? lease.reservations[0].min || 1 : ''} node{(lease.reservations[0].min || 1) !== 1 ? 's' : ''}
                                  </span>
                                )}
                              </div>
                            </div>
                          </label>
                        );
                      })
                    )}
                  </div>
                </div>
              )}
              {chiEditorTab === 'servers' && (
                <div>
                  <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 6px' }}>Add Server</h5>
                  <select className="chi-form-input" value={nodeSite} onChange={e => { setNodeSite(e.target.value); setNodeType(''); setNodeImage(''); }} style={{ marginBottom: 4, fontSize: 11 }}>
                    {configuredSites.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
                  </select>
                  <ChameleonNodeTypeComboBox nodeTypes={nodeTypes} value={nodeType} onSelect={setNodeType} disabled={loadingData} compact />
                  <div style={{ marginTop: 4 }}>
                    <ChameleonImageComboBox images={images} value={nodeImage} onSelect={setNodeImage} disabled={loadingData} compact />
                  </div>
                  <button className="chi-editor-deploy-btn" disabled={!nodeType || !nodeImage || addingNode} onClick={handleAddNode} style={{ marginTop: 4 }}>
                    {addingNode ? 'Adding...' : '+ Add Server'}
                  </button>
                  {draft.nodes.length > 0 ? (
                    <div style={{ marginTop: 12 }}>
                      <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 4px' }}>Servers ({draft.nodes.length})</h5>
                      {draft.nodes.map(n => {
                        const siteNets = existingNetworks.filter(net => net.site === (n.site || draft.site));
                        return (
                          <div key={n.id} className="chi-editor-item" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 4 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <span style={{ fontWeight: 600, flex: 1 }}>{n.name}</span>
                              <span style={{ fontSize: 10, color: 'var(--fabric-text-muted)' }}>{n.node_type}</span>
                              {n.site && <span style={{ fontSize: 9, color: 'var(--fabric-success, #39B54A)' }}>@{n.site}</span>}
                              <button className="chi-editor-item-remove" onClick={() => handleRemoveNode(n.id)}>×</button>
                            </div>
                            {/* Network interface dropdowns — one per NIC */}
                            {((n as any).interfaces || [{ nic: 0, network: (n as any).network || null }, { nic: 1, network: null }]).map((ifc: any, ifcIdx: number) => (
                              <div key={ifcIdx} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, marginTop: ifcIdx > 0 ? 2 : 0 }}>
                                <span style={{ fontWeight: 600, color: 'var(--fabric-text-muted)', minWidth: 36 }}>NIC {ifc.nic ?? ifcIdx}:</span>
                                <select
                                  style={{ flex: 1, fontSize: 10, padding: '2px 4px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)' }}
                                  value={ifc.network?.id || ''}
                                  onChange={async (e) => {
                                    if (!draft) return;
                                    const netId = e.target.value;
                                    const net = netId ? siteNets.find(sn => sn.id === netId) : null;
                                    const network = net ? { id: net.id, name: net.name } : null;
                                    const ifaces = (n as any).interfaces || [{ nic: 0, network: (n as any).network || null }, { nic: 1, network: null }];
                                    const updated_ifaces = ifaces.map((f: any, i: number) => i === ifcIdx ? { ...f, network } : f);
                                    try {
                                      const draftId = draft.id;
                                      const updated = await api.updateChameleonNodeInterfaces(draftId, n.id, updated_ifaces);
                                      setDraft(updated);
                                      onDraftUpdated?.(updated);
                                      refreshGraph(draftId);
                                    } catch (err: any) {
                                      onError?.(err?.message || 'Failed to update interface');
                                    }
                                  }}
                                >
                                  <option value="">-- Unconnected --</option>
                                  {siteNets.map(sn => (
                                    <option key={sn.id} value={sn.id}>
                                      {sn.name}{sn.shared ? ' (shared)' : ''}{sn.subnet_details?.[0]?.cidr ? ` [${sn.subnet_details[0].cidr}]` : ''}
                                    </option>
                                  ))}
                                </select>
                              </div>
                            ))}
                            <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, marginTop: 2 }}>
                              <span style={{ fontSize: 9, whiteSpace: 'nowrap', color: 'var(--fabric-text-muted)' }}>Floating IP:</span>
                              <select
                                value={fipHasNode(draft.floating_ips || [], n.id) ? String(fipGetNic(draft.floating_ips || [], n.id)) : 'none'}
                                onChange={async (e) => {
                                  if (!draft) return;
                                  const val = e.target.value;
                                  const newFips = val === 'none'
                                    ? fipRemove(draft.floating_ips || [], n.id)
                                    : fipAdd(draft.floating_ips || [], n.id, parseInt(val));
                                  try {
                                    const updated = await api.setDraftFloatingIps(draft.id, newFips);
                                    setDraft(updated);
                                    onDraftUpdated?.(updated);
                                  } catch {}
                                }}
                                style={{ fontSize: 9, padding: '1px 4px', borderRadius: 3, border: '1px solid var(--fabric-border)', minWidth: 80 }}
                              >
                                <option value="none">None</option>
                                {(n.interfaces || []).map((ifc: any, idx: number) => (
                                  <option key={idx} value={String(ifc.nic ?? idx)}>
                                    NIC {ifc.nic ?? idx}{ifc.network ? ` (${ifc.network.name})` : ''}
                                  </option>
                                ))}
                              </select>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', marginTop: 8 }}>No servers yet. Select a type and image above.</div>
                  )}
                  {/* Add Existing Server — appears when slice has resources (Active state) */}
                  {draft.resources && draft.resources.length > 0 && (
                    <div style={{ marginTop: 12, borderTop: '1px solid var(--fabric-border)', paddingTop: 8 }}>
                      <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 6px' }}>Add Existing Server</h5>
                      <button
                        className="chi-editor-deploy-btn"
                        style={{ width: '100%', marginBottom: 6 }}
                        disabled={loadingUnaffiliated}
                        onClick={async () => {
                          setLoadingUnaffiliated(true);
                          try {
                            const instances = await api.listUnaffiliatedChameleonInstances();
                            setUnaffiliatedInstances(instances);
                            if (instances.length === 0) onError?.('No unaffiliated servers found');
                          } catch (e: any) {
                            onError?.(e.message || 'Failed to find unaffiliated servers');
                          } finally {
                            setLoadingUnaffiliated(false);
                          }
                        }}
                      >
                        {loadingUnaffiliated ? 'Searching...' : 'Find Unaffiliated Servers'}
                      </button>
                      {unaffiliatedInstances.length > 0 && (
                        <>
                          <select
                            className="chi-form-input"
                            value={selectedUnaffiliated}
                            onChange={e => setSelectedUnaffiliated(e.target.value)}
                            style={{ marginBottom: 4, fontSize: 11 }}
                          >
                            <option value="">-- Select Server --</option>
                            {unaffiliatedInstances.map(inst => (
                              <option key={inst.id} value={inst.id}>
                                {inst.name} ({inst.site} - {inst.status})
                              </option>
                            ))}
                          </select>
                          <button
                            className="chi-editor-deploy-btn"
                            style={{ width: '100%' }}
                            disabled={!selectedUnaffiliated || addingExistingServer}
                            onClick={async () => {
                              if (!draft || !selectedUnaffiliated) return;
                              setAddingExistingServer(true);
                              try {
                                const inst = unaffiliatedInstances.find(i => i.id === selectedUnaffiliated);
                                const updated = await api.addChameleonSliceResource(draft.id, {
                                  type: 'instance',
                                  id: selectedUnaffiliated,
                                  name: inst?.name || 'server',
                                  site: inst?.site || '',
                                });
                                setDraft(updated);
                                onDraftUpdated?.(updated);
                                setSelectedUnaffiliated('');
                                setUnaffiliatedInstances([]);
                              } catch (e: any) {
                                onError?.(e.message || 'Failed to add server to slice');
                              } finally {
                                setAddingExistingServer(false);
                              }
                            }}
                          >
                            {addingExistingServer ? 'Adding...' : 'Add to Slice'}
                          </button>
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}
              {chiEditorTab === 'networks' && (
                <div>
                  <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 6px' }}>Attach to Existing Network</h5>
                  <select className="chi-form-input" value={selectedExistingNet} onChange={e => setSelectedExistingNet(e.target.value)}>
                    <option value="">-- Select Network --</option>
                    {existingNetworks.map(n => (
                      <option key={n.id} value={n.id}>
                        {n.name}{n.shared ? ' (shared)' : ''}{n.subnet_details?.[0]?.cidr ? ` \u2014 ${n.subnet_details[0].cidr}` : ''}
                      </option>
                    ))}
                  </select>
                  {selectedExistingNet && draft && draft.nodes.length > 0 && (
                    <>
                      <label style={{ fontSize: 10, fontWeight: 600, display: 'block', marginTop: 6, marginBottom: 2 }}>Connect Nodes:</label>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {draft.nodes.map(n => (
                          <label key={n.id} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, cursor: 'pointer' }}>
                            <input type="checkbox" checked={existingNetNodes.includes(n.id)} onChange={e => {
                              if (e.target.checked) setExistingNetNodes(prev => [...prev, n.id]);
                              else setExistingNetNodes(prev => prev.filter(id => id !== n.id));
                            }} />
                            {n.name}
                          </label>
                        ))}
                      </div>
                    </>
                  )}
                  <button className="chi-editor-deploy-btn" disabled={!selectedExistingNet} onClick={async () => {
                    if (!draft || !selectedExistingNet) return;
                    const net = existingNetworks.find(n => n.id === selectedExistingNet);
                    try {
                      const updated = await api.addChameleonDraftNetwork(draft.id, {
                        name: net?.name || 'existing-net',
                        connected_nodes: existingNetNodes,
                      });
                      setDraft(updated);
                      onDraftUpdated?.(updated);
                      refreshGraph(draft.id);
                      setSelectedExistingNet('');
                      setExistingNetNodes([]);
                    } catch (e: any) { onError?.(e.message); }
                  }} style={{ marginTop: 4 }}>
                    Attach Network
                  </button>
                  <div style={{ borderBottom: '1px solid var(--fabric-border)', margin: '12px 0' }} />
                  <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 6px' }}>Add Network</h5>
                  <input className="chi-form-input" value={netName} onChange={e => setNetName(e.target.value)} placeholder="Network name" />
                  {draft.nodes.length > 0 && (
                    <>
                      <label style={{ fontSize: 10, fontWeight: 600, display: 'block', marginTop: 6, marginBottom: 2 }}>Connect Nodes:</label>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {draft.nodes.map(n => (
                          <label key={n.id} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, cursor: 'pointer' }}>
                            <input type="checkbox" checked={netConnected.includes(n.id)} onChange={(e) => {
                              if (e.target.checked) setNetConnected(prev => [...prev, n.id]);
                              else setNetConnected(prev => prev.filter(id => id !== n.id));
                            }} />
                            {n.name}
                          </label>
                        ))}
                      </div>
                    </>
                  )}
                  <button className="chi-editor-deploy-btn" disabled={!netName || addingNet} onClick={handleAddNetwork} style={{ marginTop: 4 }}>
                    {addingNet ? 'Adding...' : '+ Add Network'}
                  </button>
                  {draft.networks.length > 0 ? (
                    <div style={{ marginTop: 12 }}>
                      <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 4px' }}>Networks ({draft.networks.length})</h5>
                      {draft.networks.map(n => (
                        <div key={n.id} className="chi-editor-item">
                          <span>{n.name}</span>
                          <button className="chi-editor-item-remove" onClick={() => handleRemoveNetwork(n.id)}>×</button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', marginTop: 8 }}>No networks yet. Enter a name above.</div>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="chi-editor-layout">
      {/* Left: Graph */}
      <div className="chi-editor-graph">
        {graphData && (graphData.nodes.length > 0 || graphData.edges.length > 0) ? (
          <CytoscapeGraph
            graph={null}
            layout={layout}
            dark={dark}
            sliceData={null}
            chameleonGraph={graphData}
            recipes={recipes}
            preserveLayout
            onLayoutChange={setLayout}
            onNodeClick={(data) => setSelectedElement(data)}
            onEdgeClick={() => {}}
            onBackgroundClick={() => setSelectedElement(null)}
            onContextAction={onContextAction || (() => {})}
          />
        ) : (
          <div className="chi-editor-empty-graph">
            <div className="chi-editor-empty-icon">
              <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
                <rect x="8" y="8" width="20" height="16" rx="3" stroke={dark ? '#5cc96a' : '#39B54A'} strokeWidth="2" fill="none" />
                <rect x="36" y="8" width="20" height="16" rx="3" stroke={dark ? '#5cc96a' : '#39B54A'} strokeWidth="2" fill="none" />
                <rect x="22" y="40" width="20" height="16" rx="3" stroke={dark ? '#5cc96a' : '#39B54A'} strokeWidth="2" fill="none" />
                <line x1="18" y1="24" x2="32" y2="40" stroke={dark ? '#5cc96a66' : '#39B54A66'} strokeWidth="1.5" />
                <line x1="46" y1="24" x2="32" y2="40" stroke={dark ? '#5cc96a66' : '#39B54A66'} strokeWidth="1.5" />
              </svg>
            </div>
            <div className="chi-editor-empty-text">
              {state === 'empty' ? 'Create a draft to start building your topology' : 'Add nodes and networks to see them here'}
            </div>
          </div>
        )}
      </div>

      {/* Right: Editor panel */}
      <div className="chi-editor-panel">
        {/* --- Empty State --- */}
        {state === 'empty' && (
          <div className="chi-editor-section">
            <h4 className="chi-editor-section-title">New Draft</h4>
            <label className="chi-form-label">Name</label>
            <input
              className="chi-form-input"
              type="text"
              value={newDraftName}
              onChange={e => setNewDraftName(e.target.value)}
              placeholder="my-experiment"
            />
            <p style={{ fontSize: 11, color: 'var(--fabric-text-muted)', margin: '8px 0 0' }}>
              Sites are selected per-node when adding servers.
            </p>
            <button
              className="chi-editor-deploy-btn"
              style={{ marginTop: 12, width: '100%' }}
              onClick={handleCreateDraft}
              disabled={!newDraftName.trim()}
            >
              Create Draft
            </button>
          </div>
        )}

        {/* --- Draft Header --- */}
        {state !== 'empty' && draft && (
          <div className="chi-editor-section chi-editor-header">
            <div className="chi-editor-header-row">
              <span className="chi-editor-draft-name">{draft.name}</span>
              <span className={`chi-status ${statusClass(stateLabel(state))}`}>{stateLabel(state)}</span>
            </div>
            <div className="chi-editor-header-meta">
              {draftSites.length > 0 ? draftSites.map(s => (
                <span key={s} style={{ background: 'rgba(57,181,74,0.15)', padding: '1px 6px', borderRadius: 8, fontSize: 10, fontWeight: 600 }}>{s}</span>
              )) : <span style={{ color: 'var(--fabric-text-muted)', fontSize: 10 }}>no sites yet</span>}
              <span>{(draft.nodes || []).length} nodes</span>
              <span>{(draft.networks || []).length} networks</span>
            </div>
            {state === 'drafting' && (
              <button
                className="chi-action-btn chi-action-btn-danger"
                style={{ marginTop: 6, fontSize: 10 }}
                onClick={handleDeleteDraft}
              >
                Discard Draft
              </button>
            )}
          </div>
        )}

        {/* --- Add Node Form --- */}
        {state === 'drafting' && draft && (
          <div className="chi-editor-section">
            <h4 className="chi-editor-section-title">Add Node</h4>
            <label className="chi-form-label">Name</label>
            <input
              className="chi-form-input"
              type="text"
              value={nodeName}
              onChange={e => setNodeName(e.target.value)}
              placeholder="node1"
            />
            <label className="chi-form-label">Site</label>
            <select className="chi-form-input" value={nodeSite} onChange={e => { setNodeSite(e.target.value); setNodeType(''); setNodeImage(''); }}>
              {configuredSites.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
            </select>
            <label className="chi-form-label">Node Type {loadingData && '(loading...)'}</label>
            <ChameleonNodeTypeComboBox nodeTypes={nodeTypes} value={nodeType} onSelect={setNodeType} disabled={loadingData} />
            <label className="chi-form-label">Image</label>
            <ChameleonImageComboBox images={images} value={nodeImage} onSelect={setNodeImage} disabled={loadingData} />
            <div className="chi-editor-form-row">
              <label className="chi-form-label">Count</label>
              <input
                className="chi-form-input"
                type="number"
                min={1}
                max={20}
                value={nodeCount}
                onChange={e => setNodeCount(Number(e.target.value))}
                style={{ width: 70 }}
              />
            </div>
            <button
              className="chi-editor-deploy-btn"
              style={{ marginTop: 8, width: '100%' }}
              onClick={handleAddNode}
              disabled={addingNode || !nodeName.trim() || !nodeType}
            >
              {addingNode ? 'Adding...' : 'Add Node'}
            </button>
          </div>
        )}

        {/* --- Node List --- */}
        {state === 'drafting' && draft && (draft.nodes || []).length > 0 && (
          <div className="chi-editor-section">
            <h4 className="chi-editor-section-title">Nodes ({(draft.nodes || []).length})</h4>
            <div className="chi-editor-item-list">
              {(draft.nodes || []).map(n => (
                <div key={n.id} className="chi-editor-item">
                  <div className="chi-editor-item-info">
                    <span className="chi-editor-item-name">{n.name}</span>
                    <span className="chi-editor-item-meta">
                      {n.node_type} / {n.image}{n.count > 1 ? ` x${n.count}` : ''}
                    </span>
                  </div>
                  <select
                    value={fipHasNode(draft.floating_ips || [], n.id) ? String(fipGetNic(draft.floating_ips || [], n.id)) : 'none'}
                    onChange={async (e) => {
                      if (!draft) return;
                      const val = e.target.value;
                      const newFips = val === 'none'
                        ? fipRemove(draft.floating_ips || [], n.id)
                        : fipAdd(draft.floating_ips || [], n.id, parseInt(val));
                      try {
                        const updated = await api.setDraftFloatingIps(draft.id, newFips);
                        setDraft(updated);
                        onDraftUpdated?.(updated);
                      } catch {}
                    }}
                    title="Floating IP NIC"
                    style={{ fontSize: 9, padding: '1px 3px', borderRadius: 3, border: '1px solid var(--fabric-border)', maxWidth: 90 }}
                  >
                    <option value="none">No FIP</option>
                    {(n.interfaces || []).map((ifc: any, idx: number) => (
                      <option key={idx} value={String(ifc.nic ?? idx)}>
                        NIC {ifc.nic ?? idx}{ifc.network ? ` (${ifc.network.name})` : ''}
                      </option>
                    ))}
                  </select>
                  <button
                    className="chi-editor-item-remove"
                    onClick={() => handleRemoveNode(n.id)}
                    title="Remove node"
                  >
                    {'\u2715'}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* --- Add Network Form --- */}
        {state === 'drafting' && draft && (draft.nodes || []).length > 0 && (
          <div className="chi-editor-section">
            <h4 className="chi-editor-section-title">Add Network</h4>
            <label className="chi-form-label">Name</label>
            <input
              className="chi-form-input"
              type="text"
              value={netName}
              onChange={e => setNetName(e.target.value)}
              placeholder="my-network"
            />
            <label className="chi-form-label">Connected Nodes</label>
            <div className="chi-editor-checkbox-list">
              {(draft.nodes || []).map(n => (
                <label key={n.id} className="chi-editor-checkbox">
                  <input
                    type="checkbox"
                    checked={netConnected.includes(n.id)}
                    onChange={() => handleToggleNetNode(n.id)}
                  />
                  {n.name}
                </label>
              ))}
            </div>
            <button
              className="chi-editor-deploy-btn"
              style={{ marginTop: 8, width: '100%' }}
              onClick={handleAddNetwork}
              disabled={addingNet || !netName.trim() || netConnected.length === 0}
            >
              {addingNet ? 'Adding...' : 'Add Network'}
            </button>
          </div>
        )}

        {/* --- Network List --- */}
        {state === 'drafting' && draft && (draft.networks || []).length > 0 && (
          <div className="chi-editor-section">
            <h4 className="chi-editor-section-title">Networks ({(draft.networks || []).length})</h4>
            <div className="chi-editor-item-list">
              {(draft.networks || []).map(net => (
                <div key={net.id} className="chi-editor-item">
                  <div className="chi-editor-item-info">
                    <span className="chi-editor-item-name">{net.name}</span>
                    <span className="chi-editor-item-meta">
                      {(net.connected_nodes || []).length} nodes connected
                    </span>
                  </div>
                  <button
                    className="chi-editor-item-remove"
                    onClick={() => handleRemoveNetwork(net.id)}
                    title="Remove network"
                  >
                    {'\u2715'}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* --- Deploy Controls --- */}
        {state === 'drafting' && draft && (draft.nodes || []).length > 0 && (
          <div className="chi-editor-section">
            <h4 className="chi-editor-section-title">Deploy</h4>
            {!showDeploy ? (
              <button
                className="chi-editor-deploy-btn"
                style={{ width: '100%' }}
                onClick={() => { setShowDeploy(true); setLeaseName(draft.name); }}
              >
                Create Lease & Deploy
              </button>
            ) : (
              <>
                <label className="chi-form-label">Lease Name</label>
                <input
                  className="chi-form-input"
                  type="text"
                  value={leaseName}
                  onChange={e => setLeaseName(e.target.value)}
                  placeholder={draft.name}
                />
                <label className="chi-form-label">Duration (hours)</label>
                <input
                  className="chi-form-input"
                  type="number"
                  min={1}
                  max={168}
                  value={durationHours}
                  onChange={e => setDurationHours(Number(e.target.value))}
                />
                <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
                  <button
                    className="chi-editor-deploy-btn"
                    style={{ flex: 1 }}
                    onClick={handleDeploy}
                    disabled={deploying}
                  >
                    {deploying ? 'Deploying...' : 'Deploy'}
                  </button>
                  <button
                    style={{ padding: '6px 10px', fontSize: 11 }}
                    onClick={() => setShowDeploy(false)}
                  >
                    Cancel
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {/* --- Deploying Status --- */}
        {state === 'deploying' && (
          <div className="chi-editor-section">
            <h4 className="chi-editor-section-title">Deployment</h4>
            <div className="chi-editor-deploy-status">
              <span className="chi-editor-spinner" />
              {deployStatus}
            </div>
          </div>
        )}

        {/* --- Deployed Mode --- */}
        {state === 'deployed' && (
          <div className="chi-editor-section">
            <h4 className="chi-editor-section-title">Deployment Complete</h4>
            <div className="chi-editor-deploy-status chi-editor-deploy-success">
              {deployStatus}
            </div>
            <p style={{ fontSize: 11, color: 'var(--fabric-text-muted)', marginTop: 8 }}>
              Switch to the Leases or Instances tab to manage your deployed resources.
            </p>
            <button
              className="chi-editor-deploy-btn"
              style={{ width: '100%', marginTop: 8 }}
              onClick={() => {
                setDraft(null);
                setGraphData(null);
                setState('empty');
                setShowDeploy(false);
                setDeployStatus('');
              }}
            >
              New Draft
            </button>
          </div>
        )}

        {/* --- Selected Element Detail --- */}
        {selectedElement && (
          <div className="chi-editor-section chi-editor-detail">
            <h4 className="chi-editor-section-title">
              Selected
              <button
                className="chi-detail-close"
                onClick={() => setSelectedElement(null)}
                style={{ float: 'right' }}
              >
                {'\u2715'}
              </button>
            </h4>
            {selectedElement.element_type === 'chameleon_instance' ? (() => {
              const fields: [string, string][] = [
                ['Name', selectedElement.name || ''],
                ['Status', selectedElement.status || ''],
                ['Site', selectedElement.site || ''],
                ['Node Type', selectedElement.node_type || ''],
                ['Image', selectedElement.image || ''],
              ];
              if (selectedElement.floating_ip) fields.push(['Floating IP', selectedElement.floating_ip]);
              if (selectedElement.ip && selectedElement.ip !== selectedElement.floating_ip) fields.push(['Private IP', selectedElement.ip]);
              if (selectedElement.instance_id) fields.push(['Instance ID', selectedElement.instance_id]);
              if (selectedElement.ssh_ready) fields.push(['SSH', selectedElement.ssh_ready === 'true' ? 'Ready' : 'Not ready']);
              return (
                <table className="chi-detail-table">
                  <tbody>
                    {fields.map(([label, val]) => (
                      <tr key={label}>
                        <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{label}</td>
                        <td style={{ fontFamily: ['Instance ID', 'Floating IP', 'Private IP'].includes(label) ? 'monospace' : 'inherit' }}>{val}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              );
            })() : (
              <table className="chi-detail-table">
                <tbody>
                  {Object.entries(selectedElement).filter(([k]) => !['bg_color', 'bg_color_dark', 'border_color', 'border_color_dark', 'parent', 'id'].includes(k)).map(([k, v]) => (
                    <tr key={k}>
                      <td>{k}</td>
                      <td>{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {/* Boot Config for deployed Chameleon instances */}
            {selectedElement.element_type === 'chameleon_instance' && selectedElement.status === 'ACTIVE' && selectedElement.instance_id && draft && (
              <ChameleonBootConfigPanel sliceId={draft.id} nodeName={selectedElement.name || ''} />
            )}
          </div>
        )}
      </div>

      {/* Confirmation modal */}
      {confirmAction && typeof document !== 'undefined' && createPortal(
        <div className="toolbar-modal-overlay" style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.5)', zIndex: 99999 }} onClick={() => setConfirmAction(null)}>
          <div className="toolbar-modal" onClick={e => e.stopPropagation()}>
            <h4>{confirmAction.title}</h4>
            <p>{confirmAction.message}</p>
            <div className="toolbar-modal-actions">
              <button onClick={() => setConfirmAction(null)}>Cancel</button>
              <button className={confirmAction.danger ? 'danger' : 'primary'} onClick={() => { confirmAction.onConfirm(); setConfirmAction(null); }}>
                {confirmAction.danger ? 'Discard' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
