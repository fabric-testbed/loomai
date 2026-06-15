'use client';
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import CytoscapeGraph from './CytoscapeGraph';
import ChameleonNodeTypeComboBox from './editor/ChameleonNodeTypeComboBox';
import ChameleonImageComboBox from './editor/ChameleonImageComboBox';
import { CompactResourceTable, FilterBox, InlineActions, matchesFilter } from './editor/ChameleonEditorUi';
import * as api from '../api/client';
import type { ChameleonSite, ChameleonImage, ChameleonDraft, ChameleonNodeTypeDetail, ChameleonNetwork, ChameleonSliceResource } from '../types/chameleon';

// --- Floating IP helpers (supports old string[] and new {node_id, nic}[] formats) ---
type FipEntry = string | { node_id: string; nic: number };
type ChameleonGraphData = { nodes: any[]; edges: any[] };
type ChameleonKeypair = {
  name?: string;
  fingerprint?: string;
  type?: string;
  _site?: string;
};

const PREFERRED_X86_NODE_TYPES = [
  'compute_skylake',
  'compute_cascadelake',
  'compute_cascadelake_r',
  'compute_icelake_r650',
  'compute_icelake_r750',
  'compute_zen3',
  'compute_haswell_ib',
  'compute_haswell',
];
const PREFERRED_X86_IMAGES = ['CC-Ubuntu22.04', 'CC-Ubuntu24.04'];
const PREFERRED_ARM_IMAGES = ['CC-Ubuntu22.04-ARM64', 'CC-Ubuntu24.04-ARM64', 'CC-Ubuntu26.04-ARM64'];

function isArmNodeType(nodeType?: ChameleonNodeTypeDetail): boolean {
  const arch = `${nodeType?.cpu_arch || ''} ${nodeType?.node_type || ''}`.toLowerCase();
  return arch.includes('arm') || arch.includes('aarch64');
}

function isGpuNodeType(nodeType?: ChameleonNodeTypeDetail): boolean {
  const value = `${nodeType?.gpu || ''} ${nodeType?.node_type || ''}`.toLowerCase();
  return value.includes('gpu');
}

function chooseDefaultNodeType(nodeTypes: ChameleonNodeTypeDetail[]): string {
  const reservable = nodeTypes.filter(nt => (nt.reservable ?? 0) > 0);
  const candidates = reservable.length > 0 ? reservable : nodeTypes;
  const x86Compute = candidates.filter(nt => !isArmNodeType(nt) && !isGpuNodeType(nt));
  for (const preferred of PREFERRED_X86_NODE_TYPES) {
    if (x86Compute.some(nt => nt.node_type === preferred)) return preferred;
  }
  return x86Compute[0]?.node_type || candidates[0]?.node_type || '';
}

function chooseDefaultImage(images: ChameleonImage[], nodeType?: ChameleonNodeTypeDetail): string {
  if (images.length === 0) return '';
  const active = images.filter(img => !img.status || img.status.toLowerCase() === 'active');
  const candidates = active.length > 0 ? active : images;
  const preferredNames = isArmNodeType(nodeType) ? PREFERRED_ARM_IMAGES : PREFERRED_X86_IMAGES;
  for (const name of preferredNames) {
    const match = candidates.find(img => img.name === name || img.id === name);
    if (match) return match.id || match.name;
  }
  const nonCuda = candidates.find(img => !`${img.name} ${img.id}`.toLowerCase().includes('cuda'));
  return nonCuda?.id || nonCuda?.name || candidates[0].id || candidates[0].name;
}

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
type ChiEditorTab = 'leases' | 'servers' | 'networks' | 'ips' | 'resources';
type ConfirmAction = {
  title: string;
  message: string;
  details?: string[];
  onConfirm: () => void | Promise<void>;
  danger?: boolean;
  confirmLabel?: string;
};

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
  /** Optional terminal opener for live Chameleon instances. */
  onOpenTerminal?: (instance: { id: string; name: string; site: string }) => void;
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

function stableGraphValue(value: any): any {
  if (Array.isArray(value)) return value.map(stableGraphValue);
  if (!value || typeof value !== 'object') return value;
  return Object.keys(value).sort().reduce<Record<string, any>>((acc, key) => {
    const next = value[key];
    if (next !== undefined) acc[key] = stableGraphValue(next);
    return acc;
  }, {});
}

function graphElementKey(element: any): string {
  return String(element?.data?.id || element?.id || '');
}

function graphSignature(graph: ChameleonGraphData | null): string {
  if (!graph) return '';
  const nodes = [...(graph.nodes || [])]
    .sort((a, b) => graphElementKey(a).localeCompare(graphElementKey(b)))
    .map(stableGraphValue);
  const edges = [...(graph.edges || [])]
    .sort((a, b) => graphElementKey(a).localeCompare(graphElementKey(b)))
    .map(stableGraphValue);
  return JSON.stringify({ nodes, edges });
}

function shortId(value?: string): string {
  if (!value) return '';
  return value.length > 12 ? `${value.slice(0, 12)}...` : value;
}

function resourceSite(resource: Partial<ChameleonSliceResource> | any, fallback = 'CHI@TACC'): string {
  return resource?.site || resource?._site || fallback;
}

function resourceProviderId(resource: Partial<ChameleonSliceResource> | any): string {
  return resource?.provider_id || resource?.id || resource?.floating_ip_id || resource?.resource_id || '';
}

function resourceDisplayName(resource: Partial<ChameleonSliceResource> | any): string {
  return resource?.name || resource?.floating_ip || resource?.floating_ip_address || resourceProviderId(resource) || 'resource';
}

function networkCidrs(network: ChameleonNetwork | any): string {
  return (network?.subnet_details || []).map((s: any) => s.cidr || s.name).filter(Boolean).join(', ');
}

// --- Component ---

export default function ChameleonEditor({ sites, onError, onDeployed, graphOnly, formsOnly, draftId: externalDraftId, onDraftUpdated, draftData: externalDraftData, draftVersion, onContextAction, recipes, autoRefresh, onOpenTerminal }: ChameleonEditorProps) {
  // Core state
  const [state, setState] = useState<EditorState>('empty');
  const [draft, setDraft] = useState<ChameleonDraft | null>(null);
  const [graphData, setGraphData] = useState<ChameleonGraphData | null>(null);
  const graphSignatureRef = useRef('');
  const setGraphDataIfChanged = useCallback((next: ChameleonGraphData | null) => {
    const nextSignature = graphSignature(next);
    if (nextSignature === graphSignatureRef.current) return;
    graphSignatureRef.current = nextSignature;
    setGraphData(next);
  }, []);

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
  const [nodeKeyName, setNodeKeyName] = useState('');
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
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  // Lease selection mode: 'new' = create a new lease at submit, 'existing' = use a pre-selected lease
  const [leaseMode, setLeaseMode] = useState<'new' | 'existing'>('new');
  // Per-site existing lease selection: { siteName: leaseId }
  const [selectedExistingLeases, setSelectedExistingLeases] = useState<Record<string, string>>({});

  // Site data (node types, images) — cached per site
  const [nodeTypes, setNodeTypes] = useState<ChameleonNodeTypeDetail[]>([]);
  const [allImages, setAllImages] = useState<ChameleonImage[]>([]);
  const [loadingData, setLoadingData] = useState(false);
  const siteDataCache = React.useRef<Record<string, { nodeTypes: ChameleonNodeTypeDetail[]; images: ChameleonImage[] }>>({});
  const [keypairsBySite, setKeypairsBySite] = useState<Record<string, ChameleonKeypair[]>>({});
  const [loadingKeypairsBySite, setLoadingKeypairsBySite] = useState<Record<string, boolean>>({});

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
  const [chiEditorTab, setChiEditorTab] = useState<ChiEditorTab>('servers');

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

  // Live resource inventory used by Networks/IPs/Resources tabs.
  const [floatingIps, setFloatingIps] = useState<any[]>([]);
  const [securityGroups, setSecurityGroups] = useState<any[]>([]);
  const [loadingInventory, setLoadingInventory] = useState(false);
  const [resourceBusy, setResourceBusy] = useState('');

  // Network management.
  const [newRealNetName, setNewRealNetName] = useState('');
  const [newRealNetSite, setNewRealNetSite] = useState('');
  const [newRealNetCidr, setNewRealNetCidr] = useState('');
  const [selectedExistingNetResource, setSelectedExistingNetResource] = useState('');

  // Floating IP management.
  const [allocFipSite, setAllocFipSite] = useState('');
  const [selectedFipId, setSelectedFipId] = useState('');
  const [selectedFipTargetPort, setSelectedFipTargetPort] = useState('');

  // Per-tab filters keep high-cardinality resource tabs scannable.
  const [leaseFilter, setLeaseFilter] = useState('');
  const [serverFilter, setServerFilter] = useState('');
  const [networkFilter, setNetworkFilter] = useState('');
  const [ipFilter, setIpFilter] = useState('');
  const [resourceFilter, setResourceFilter] = useState('');

  // Auto-reset image when filtered images change and current selection is invalid
  useEffect(() => {
    if (images.length > 0 && nodeImage && !images.find(img => img.id === nodeImage || img.name === nodeImage)) {
      setNodeImage(chooseDefaultImage(images, selectedNodeTypeDetail));
    }
  }, [images, nodeImage, selectedNodeTypeDetail]);

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
        setGraphDataIfChanged(null);
      }
      return;
    }
    // Always clear graph immediately on slice switch so stale topology disappears
    setGraphDataIfChanged(null);
    // If parent already provided externalDraftData for this id, use it directly
    if (externalDraftData && externalDraftData.id === externalDraftId) {
      setDraft(externalDraftData);
      setState(externalDraftData.state === 'Active' ? 'deployed' : externalDraftData.state === 'Deploying' ? 'deploying' : 'drafting');
      buildLocalGraph(externalDraftData);
      api.getChameleonDraftGraph(externalDraftId).then(g => setGraphDataIfChanged(g)).catch(() => setGraphDataIfChanged(null));
      return;
    }
    // Otherwise load fresh
    api.getChameleonDraft(externalDraftId).then(d => {
      setDraft(d);
      setState('drafting');
      buildLocalGraph(d);
      api.getChameleonDraftGraph(externalDraftId).then(g => setGraphDataIfChanged(g)).catch(() => setGraphDataIfChanged(null));
    }).catch(err => {
      onError?.(`Failed to load draft: ${err.message}`);
    });
  }, [externalDraftId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync external draft data changes — triggered by draftVersion counter
  // Every time the side panel adds/removes a node, polling updates state, etc.
  useEffect(() => {
    if (!externalDraftData || !externalDraftId) return;
    setDraft(externalDraftData);
    setState(externalDraftData.state === 'Active' ? 'deployed' : externalDraftData.state === 'Deploying' ? 'deploying' : 'drafting');
    if (!graphSignatureRef.current) {
      buildLocalGraph(externalDraftData);
    }
    // Fetch enriched graph from backend, but keep the current graph object when
    // polling returns the same topology/status payload.
    api.getChameleonDraftGraph(externalDraftId).then(g => setGraphDataIfChanged(g)).catch(() => {});
  }, [draftVersion, externalDraftId, externalDraftData, setGraphDataIfChanged]); // eslint-disable-line react-hooks/exhaustive-deps

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

  useEffect(() => {
    const preferred = draftSites[0] || configuredSites[0]?.name || '';
    if (preferred && !newRealNetSite) setNewRealNetSite(preferred);
    if (preferred && !allocFipSite) setAllocFipSite(preferred);
  }, [draftSites, configuredSites, newRealNetSite, allocFipSite]);

  // Load node types and images when the per-node site changes (with caching)
  const effectiveSite = nodeSite || configuredSites[0]?.name || '';
  useEffect(() => {
    if (!effectiveSite) return;
    // Check cache first
    const cached = siteDataCache.current[effectiveSite];
    if (cached) {
      const defaultNodeType = chooseDefaultNodeType(cached.nodeTypes);
      const defaultNodeTypeDetail = cached.nodeTypes.find(nt => nt.node_type === defaultNodeType);
      setNodeTypes(cached.nodeTypes);
      setAllImages(cached.images);
      if (defaultNodeType) setNodeType(defaultNodeType);
      if (cached.images.length > 0) setNodeImage(chooseDefaultImage(cached.images, defaultNodeTypeDetail));
      return;
    }
    setLoadingData(true);
    Promise.all([
      api.getChameleonNodeTypesDetail(effectiveSite).then(d => d.node_types || []).catch(() => []),
      api.getChameleonImages(effectiveSite).catch(() => []),
    ]).then(([nt, img]) => {
      const defaultNodeType = chooseDefaultNodeType(nt);
      const defaultNodeTypeDetail = nt.find(t => t.node_type === defaultNodeType);
      siteDataCache.current[effectiveSite] = { nodeTypes: nt, images: img };
      setNodeTypes(nt);
      setAllImages(img);
      if (defaultNodeType) setNodeType(defaultNodeType);
      if (img.length > 0) setNodeImage(chooseDefaultImage(img, defaultNodeTypeDetail));
    }).finally(() => setLoadingData(false));
  }, [effectiveSite]);

  const loadKeypairsForSite = useCallback(async (siteName: string) => {
    if (!siteName) return;
    setLoadingKeypairsBySite(prev => ({ ...prev, [siteName]: true }));
    try {
      const keypairs = await api.listChameleonKeypairs(siteName);
      setKeypairsBySite(prev => ({ ...prev, [siteName]: keypairs || [] }));
    } catch {
      setKeypairsBySite(prev => ({ ...prev, [siteName]: [] }));
    } finally {
      setLoadingKeypairsBySite(prev => ({ ...prev, [siteName]: false }));
    }
  }, []);

  const getKeypairNamesForSite = useCallback((siteName: string, selectedKey = ''): string[] => {
    const names = Array.from(new Set(
      (keypairsBySite[siteName] || [])
        .map(keypair => keypair.name || '')
        .filter(Boolean),
    ));
    if (selectedKey && !names.includes(selectedKey)) names.push(selectedKey);
    return names;
  }, [keypairsBySite]);

  useEffect(() => {
    const sitesToLoad = new Set([effectiveSite, ...draftSites].filter(Boolean));
    for (const siteName of sitesToLoad) {
      if (keypairsBySite[siteName] === undefined && !loadingKeypairsBySite[siteName]) {
        void loadKeypairsForSite(siteName);
      }
    }
  }, [
    effectiveSite,
    draftSites,
    keypairsBySite,
    loadingKeypairsBySite,
    loadKeypairsForSite,
  ]);

  // Fetch existing networks from all sites in draft
  useEffect(() => {
    if (draftSites.length === 0) return;
    Promise.all(draftSites.map(s => api.listChameleonNetworks(s).catch(() => [] as ChameleonNetwork[])))
      .then(results => setExistingNetworks(results.flat()));
  }, [draftSites.join(',')]);

  const inventorySites = useMemo(
    () => draftSites.length > 0 ? draftSites : configuredSites.map(s => s.name),
    [draftSites, configuredSites],
  );

  const refreshResourceInventory = useCallback(async () => {
    const sitesToLoad = inventorySites.length > 0 ? inventorySites : undefined;
    setLoadingInventory(true);
    try {
      const [networkResults, fipResults, sgResults] = await Promise.all([
        sitesToLoad
          ? Promise.all(sitesToLoad.map(s => api.listChameleonNetworks(s).catch(() => [] as ChameleonNetwork[]))).then(r => r.flat())
          : api.listChameleonNetworks().catch(() => [] as ChameleonNetwork[]),
        sitesToLoad
          ? Promise.all(sitesToLoad.map(s => api.listChameleonFloatingIps(s).catch(() => [] as any[]))).then(r => r.flat())
          : api.listChameleonFloatingIps().catch(() => [] as any[]),
        sitesToLoad
          ? Promise.all(sitesToLoad.map(s => api.listChameleonSecurityGroups(s).catch(() => [] as any[]))).then(r => r.flat())
          : api.listChameleonSecurityGroups().catch(() => [] as any[]),
      ]);
      setExistingNetworks(networkResults);
      setFloatingIps(fipResults);
      setSecurityGroups(sgResults);
    } finally {
      setLoadingInventory(false);
    }
  }, [inventorySites.join(',')]);

  useEffect(() => {
    if (!formsOnly) return;
    if (!['networks', 'ips', 'resources'].includes(chiEditorTab)) return;
    refreshResourceInventory().catch((e: any) => onError?.(e?.message || 'Failed to refresh Chameleon resources'));
  }, [formsOnly, chiEditorTab, refreshResourceInventory, onError]);

  // Fetch available leases when Leases tab is shown (or refresh on demand)
  const refreshAvailableLeases = useCallback(async () => {
    if (draftSites.length === 0) return;
    setLoadingLeases(true);
    try {
      const results = await Promise.all(draftSites.map(s => api.listChameleonLeases(s).catch(() => [] as any[])));
      setAvailableLeases(results.flat());
    } finally {
      setLoadingLeases(false);
    }
  }, [draftSites.join(',')]);

  useEffect(() => {
    if (chiEditorTab !== 'leases' || !formsOnly || draftSites.length === 0) return;
    refreshAvailableLeases();
  }, [chiEditorTab, formsOnly, draftSites.join(','), refreshAvailableLeases]);

  // Pre-create lease state
  const [precreating, setPrecreating] = useState(false);
  const [precreateStatus, setPrecreateStatus] = useState('');

  // Edit-in-place state for existing nodes
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
  const [editNodeName, setEditNodeName] = useState('');
  const [editNodeType, setEditNodeType] = useState('');
  const [editNodeImage, setEditNodeImage] = useState('');
  const [editNodeKeyName, setEditNodeKeyName] = useState('');
  const [savingNodeEdit, setSavingNodeEdit] = useState(false);

  const startEditNode = useCallback((node: any) => {
    setEditingNodeId(node.id);
    setEditNodeName(node.name || '');
    setEditNodeType(node.node_type || '');
    setEditNodeImage(node.image || '');
    setEditNodeKeyName(node.key_name || '');
    // Load site data so the type/image dropdowns are populated for this node's site
    if (node.site && node.site !== nodeSite) {
      setNodeSite(node.site);
    }
  }, [nodeSite]);

  const cancelEditNode = useCallback(() => {
    setEditingNodeId(null);
    setEditNodeName('');
    setEditNodeType('');
    setEditNodeImage('');
    setEditNodeKeyName('');
  }, []);

  const saveNodeEdit = useCallback(async () => {
    if (!draft || !editingNodeId) return;
    setSavingNodeEdit(true);
    try {
      const updated = await api.updateChameleonDraftNode(draft.id, editingNodeId, {
        name: editNodeName,
        node_type: editNodeType,
        image: editNodeImage,
        key_name: editNodeKeyName || '',
      });
      setDraft(updated);
      onDraftUpdated?.(updated);
      refreshGraph(draft.id);
      cancelEditNode();
    } catch (e: any) {
      onError?.(e?.message || 'Failed to update node');
    } finally {
      setSavingNodeEdit(false);
    }
  }, [draft, editingNodeId, editNodeName, editNodeType, editNodeImage, editNodeKeyName, onDraftUpdated, onError, cancelEditNode]);

  const handlePrecreateLease = useCallback(async () => {
    if (!draft) return;
    setPrecreating(true);
    setPrecreateStatus('Creating lease(s)...');
    try {
      const result = await api.precreateLeasesForDraft(draft.id, {
        lease_name: leaseName || draft.name,
        duration_hours: durationHours,
      });
      // Refresh available leases so the new ones appear in the dropdown
      await refreshAvailableLeases();
      // Switch to "existing lease" mode and pre-select the newly created leases
      const newSelections: Record<string, string> = {};
      for (const l of result.leases) {
        newSelections[l.site] = l.lease_id;
      }
      setSelectedExistingLeases(prev => ({ ...prev, ...newSelections }));
      setLeaseMode('existing');
      const count = result.leases.length;
      setPrecreateStatus(`Created ${count} lease${count !== 1 ? 's' : ''}. Click Submit to deploy.`);
      if (result.errors && result.errors.length) {
        onError?.(result.errors.join('; '));
      }
    } catch (e: any) {
      setPrecreateStatus('');
      onError?.(e?.message || 'Failed to pre-create lease');
    } finally {
      setPrecreating(false);
    }
  }, [draft, leaseName, durationHours, refreshAvailableLeases, onError]);

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
    if (!id) { setGraphDataIfChanged(null); return; }
    try {
      const g = await api.getChameleonDraftGraph(id);
      setGraphDataIfChanged(g);
    } catch {
      // If graph endpoint fails, build a simple graph from draft data
      if (draft) {
        buildLocalGraph(draft);
      }
    }
  }, [draft, setGraphDataIfChanged]);

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
          element_type: 'chameleon_instance',
          testbed: 'Chameleon',
          draft_id: d.id,
          node_id: n.id,
          planned_node_id: n.id,
          name: n.name,
          site: n.site || '',
          status: n.status || 'DRAFT',
          instance_id: n.instance_id || '',
          floating_ip: n.floating_ip || '',
          ip: n.management_ip || '',
          node_type: n.node_type || '',
          image: n.image || '',
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
        data: {
          id: `net-${net.id}`,
          label: net.name,
          element_type: 'network',
          testbed: 'Chameleon',
          draft_id: d.id,
          network_id: net.id,
          deletable: 'true',
          name: net.name,
        },
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
              data: {
                id: netNodeId,
                label: ifc.network.name,
                element_type: 'network',
                testbed: 'Chameleon',
                draft_id: d.id,
                network_id: ifc.network.id,
                deletable: 'false',
                name: ifc.network.name,
                net_type: isFabNet ? 'FABNetv4' : '',
              },
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

    setGraphDataIfChanged({ nodes, edges });
  }, [setGraphDataIfChanged]);

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
        setGraphDataIfChanged(null);
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
        ...(nodeKeyName ? { key_name: nodeKeyName } : {}),
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
      setNodeKeyName('');
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
  }, [draft, nodeName, nodeType, nodeImage, nodeCount, nodeSite, effectiveSite, nodeKeyName, refreshGraph, onError]);

  const handleRemoveNode = useCallback(async (nodeId: string) => {
    if (!draft) return;
    const node = draft.nodes.find(n => n.id === nodeId);
    const details: string[] = [];
    if (fipHasNode(draft.floating_ips || [], nodeId)) details.push('Floating IP intent for this server will be cleared.');
    for (const net of draft.networks || []) {
      if ((net.connected_nodes || []).includes(nodeId)) details.push(`Draft network membership will be removed: ${net.name}`);
    }
    setConfirmAction({
      title: 'Remove From Draft',
      message: `Remove planned server "${node?.name || nodeId}" from this Chameleon slice draft? This does not delete any live Chameleon instance.`,
      details,
      danger: true,
      confirmLabel: 'Remove from draft',
      onConfirm: async () => {
        try {
          const updated = await api.removeChameleonDraftNode(draft.id, nodeId);
          setDraft(updated);
          onDraftUpdated?.(updated);
          buildLocalGraph(updated);
          refreshGraph(draft.id);
        } catch (e: any) {
          onError?.(e.message || 'Failed to remove node');
        }
      },
    });
  }, [draft, refreshGraph, buildLocalGraph, onDraftUpdated, onError]);

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
    const network = draft.networks.find(n => n.id === networkId);
    setConfirmAction({
      title: 'Remove Draft Network',
      message: `Remove draft network "${network?.name || networkId}" from this Chameleon slice? This only edits LoomAI draft topology.`,
      danger: true,
      confirmLabel: 'Remove from draft',
      onConfirm: async () => {
        try {
          const updated = await api.removeChameleonDraftNetwork(draft.id, networkId);
          setDraft(updated);
          onDraftUpdated?.(updated);
          buildLocalGraph(updated);
          refreshGraph(draft.id);
        } catch (e: any) {
          onError?.(e.message || 'Failed to remove network');
        }
      },
    });
  }, [draft, refreshGraph, buildLocalGraph, onDraftUpdated, onError]);

  const handleToggleNetNode = useCallback((nodeId: string) => {
    setNetConnected(prev =>
      prev.includes(nodeId) ? prev.filter(n => n !== nodeId) : [...prev, nodeId]
    );
  }, []);

  const handleDeploy = useCallback(async () => {
    if (!draft) return;
    setDeploying(true);
    setState('deploying');
    try {
      const params: any = {
        lease_name: leaseName || draft.name,
        duration_hours: durationHours,
      };
      if (leaseMode === 'existing') {
        // Validate: every site in the draft must have a selected existing lease
        const missingSites = draftSites.filter(s => !selectedExistingLeases[s]);
        if (missingSites.length > 0) {
          throw new Error(`Select an existing lease for: ${missingSites.join(', ')}`);
        }
        params.existing_lease_ids = selectedExistingLeases;
        setDeployStatus('Attaching existing lease...');
      } else {
        setDeployStatus('Creating lease...');
      }
      const result = await api.deployChameleonDraft(draft.id, params);
      const leaseCount = result.leases?.length || 0;
      const firstLease = result.leases?.[0];
      setDeployStatus(`${leaseCount} lease${leaseCount !== 1 ? 's' : ''} ${leaseMode === 'existing' ? 'attached' : 'created'}${firstLease ? ` (${firstLease.status})` : ''}`);
      setState('deployed');
      onDeployed?.(firstLease?.lease_id || '');
    } catch (e: any) {
      setDeployStatus(`Deployment failed: ${e.message}`);
      setState('drafting');
      onError?.(e.message || 'Deployment failed');
    } finally {
      setDeploying(false);
    }
  }, [draft, leaseName, durationHours, leaseMode, selectedExistingLeases, draftSites, onDeployed, onError]);

  const applyUpdatedDraft = useCallback((updated: ChameleonDraft, options?: { refresh?: boolean }) => {
    setDraft(updated);
    onDraftUpdated?.(updated);
    buildLocalGraph(updated);
    if (options?.refresh !== false) refreshGraph(updated.id);
  }, [buildLocalGraph, onDraftUpdated, refreshGraph]);

  const sliceResources = draft?.resources || [];
  const leaseResources = useMemo(
    () => sliceResources.filter(r => r.type === 'lease'),
    [sliceResources],
  );
  const instanceResources = useMemo(
    () => sliceResources.filter(r => r.type === 'instance'),
    [sliceResources],
  );
  const networkResources = useMemo(
    () => sliceResources.filter(r => r.type === 'network'),
    [sliceResources],
  );
  const floatingIpResources = useMemo(
    () => sliceResources.filter(r => r.type === 'floating_ip'),
    [sliceResources],
  );
  const securityGroupResources = useMemo(
    () => sliceResources.filter(r => r.type === 'security_group'),
    [sliceResources],
  );

  const trackedNetworkIds = useMemo(
    () => new Set(networkResources.map(r => resourceProviderId(r)).filter(Boolean)),
    [networkResources],
  );
  const trackedFloatingIpIds = useMemo(
    () => new Set(floatingIpResources.map(r => resourceProviderId(r)).filter(Boolean)),
    [floatingIpResources],
  );
  const trackedSecurityGroupIds = useMemo(
    () => new Set(securityGroupResources.map(r => resourceProviderId(r)).filter(Boolean)),
    [securityGroupResources],
  );

  const liveServerTargets = useMemo(
    () => instanceResources
      .filter(r => resourceProviderId(r))
      .map(r => ({
        id: resourceProviderId(r),
        name: r.name || resourceProviderId(r),
        site: resourceSite(r),
        portId: r.port_id || '',
        floatingIp: r.floating_ip || '',
        ip: (r.ip_addresses || [])[0] || r.management_ip || '',
        status: r.status || '',
      })),
    [instanceResources],
  );

  const filteredLeaseResources = useMemo(
    () => leaseResources.filter(r => matchesFilter(leaseFilter, [
      r.name, r.id, r.provider_id, r.resource_id, r.status, r.site, r.ownership,
    ])),
    [leaseResources, leaseFilter],
  );
  const filteredAvailableLeases = useMemo(
    () => availableLeases.filter(lease => matchesFilter(leaseFilter, [
      lease.name, lease.id, lease.status, lease.site, lease._site,
      lease.reservations?.map((r: any) => [r.resource_type, r.min, r.max]),
    ])),
    [availableLeases, leaseFilter],
  );
  const filteredPlannedNodes = useMemo(
    () => (draft?.nodes || []).filter(n => matchesFilter(serverFilter, [
      n.name, n.id, n.site, n.node_type, n.image, n.interfaces?.map((ifc: any) => ifc.network?.name),
    ])),
    [draft, serverFilter],
  );
  const filteredInstanceResources = useMemo(
    () => instanceResources.filter(r => matchesFilter(serverFilter, [
      r.name, resourceProviderId(r), r.site, r.status, r.ownership, r.floating_ip,
      r.management_ip, r.ip_addresses,
    ])),
    [instanceResources, serverFilter],
  );
  const filteredUnaffiliatedInstances = useMemo(
    () => unaffiliatedInstances.filter(inst => matchesFilter(serverFilter, [
      inst.name, inst.id, inst.site, inst.status, inst.floating_ip, inst.ip_addresses,
    ])),
    [unaffiliatedInstances, serverFilter],
  );
  const filteredExistingNetworkResources = useMemo(
    () => existingNetworks
      .filter(n => !trackedNetworkIds.has(n.id))
      .filter(n => matchesFilter(networkFilter, [
        n.name, n.id, n.site, n.status, n.shared ? 'shared' : 'private', networkCidrs(n),
      ])),
    [existingNetworks, trackedNetworkIds, networkFilter],
  );
  const filteredNetworkResources = useMemo(
    () => networkResources.filter(r => matchesFilter(networkFilter, [
      r.name, resourceProviderId(r), r.site, r.status, r.ownership, r.cidr,
    ])),
    [networkResources, networkFilter],
  );
  const filteredDraftNetworks = useMemo(
    () => (draft?.networks || []).filter(n => matchesFilter(networkFilter, [
      n.name, n.id, n.connected_nodes,
    ])),
    [draft, networkFilter],
  );
  const filteredIpIntentNodes = useMemo(
    () => (draft?.nodes || []).filter(n => matchesFilter(ipFilter, [
      n.name, n.id, n.site, n.interfaces?.map((ifc: any) => ifc.network?.name),
    ])),
    [draft, ipFilter],
  );
  const filteredFloatingIps = useMemo(
    () => floatingIps
      .filter(ip => !trackedFloatingIpIds.has(ip.id))
      .filter(ip => matchesFilter(ipFilter, [
        ip.floating_ip_address, ip.id, ip.status, ip.site, ip._site, ip.port_id,
      ])),
    [floatingIps, trackedFloatingIpIds, ipFilter],
  );
  const filteredFloatingIpResources = useMemo(
    () => floatingIpResources.filter(r => matchesFilter(ipFilter, [
      r.name, resourceProviderId(r), r.floating_ip, r.site, r.status, r.ownership, r.port_id,
    ])),
    [floatingIpResources, ipFilter],
  );
  const filteredSliceResources = useMemo(
    () => sliceResources.filter(r => matchesFilter(resourceFilter, [
      r.type, resourceDisplayName(r), resourceProviderId(r), r.site, r.status, r.ownership,
      r.managed ? 'managed' : 'imported', r.delete_with_slice ? 'delete with slice' : 'detach only',
    ])),
    [sliceResources, resourceFilter],
  );
  const filteredAttachableSecurityGroups = useMemo(
    () => securityGroups
      .filter(sg => !trackedSecurityGroupIds.has(sg.id))
      .filter(sg => matchesFilter(resourceFilter, [
        sg.name, sg.id, sg.site, sg._site, sg.description, (sg.security_group_rules || []).length,
      ])),
    [securityGroups, trackedSecurityGroupIds, resourceFilter],
  );

  const leaseDetachDetails = useCallback((lease: ChameleonSliceResource): string[] => {
    const leaseId = lease.id || lease.provider_id || lease.lease_id;
    if (!leaseId) return [];
    return sliceResources
      .filter(r => r.resource_id !== lease.resource_id && (r.lease_id === leaseId || r.relationship?.lease_id === leaseId))
      .map(r => `${r.type}: ${resourceDisplayName(r)} (${shortId(resourceProviderId(r))})`);
  }, [sliceResources]);

  const plannedNodeRemovalDetails = useCallback((nodeId: string): string[] => {
    const details: string[] = [];
    if (fipHasNode(draft?.floating_ips || [], nodeId)) details.push('Floating IP intent for this server will be cleared.');
    for (const net of draft?.networks || []) {
      if ((net.connected_nodes || []).includes(nodeId)) details.push(`Draft network membership will be removed: ${net.name}`);
    }
    return details;
  }, [draft]);

  const confirmEditorAction = useCallback((action: ConfirmAction) => {
    setConfirmAction(action);
  }, []);

  const detachSliceResource = useCallback(async (resource: ChameleonSliceResource) => {
    if (!draft || !resource.resource_id) return;
    setResourceBusy(resource.resource_id);
    try {
      const updated = await api.removeChameleonSliceResource(draft.id, resource.resource_id);
      applyUpdatedDraft(updated);
    } catch (e: any) {
      onError?.(e?.message || 'Failed to detach resource');
    } finally {
      setResourceBusy('');
    }
  }, [draft, applyUpdatedDraft, onError]);

  const deleteSliceResource = useCallback(async (resource: ChameleonSliceResource) => {
    if (!draft) return;
    const id = resourceProviderId(resource);
    const site = resourceSite(resource);
    setResourceBusy(resource.resource_id || id);
    try {
      if (resource.type === 'lease') {
        await api.deleteChameleonLease(id, site);
      } else if (resource.type === 'instance') {
        await api.deleteChameleonInstance(id, site);
      } else if (resource.type === 'network') {
        await api.deleteChameleonNetwork(id, site);
      } else if (resource.type === 'floating_ip') {
        await api.releaseChameleonFloatingIp(id, site);
      } else if (resource.type === 'security_group') {
        await api.deleteChameleonSecurityGroup(id, site);
      }
      if (resource.resource_id) {
        const updated = await api.removeChameleonSliceResource(draft.id, resource.resource_id);
        applyUpdatedDraft(updated);
      }
      await refreshResourceInventory();
    } catch (e: any) {
      onError?.(e?.message || 'Failed to delete resource');
    } finally {
      setResourceBusy('');
    }
  }, [draft, applyUpdatedDraft, refreshResourceInventory, onError]);

  const toggleDeleteWithSlice = useCallback(async (resource: ChameleonSliceResource) => {
    if (!draft) return;
    setResourceBusy(resource.resource_id || resourceProviderId(resource));
    try {
      const updated = await api.addChameleonSliceResource(draft.id, {
        ...resource,
        delete_with_slice: !resource.delete_with_slice,
      });
      applyUpdatedDraft(updated, { refresh: false });
    } catch (e: any) {
      onError?.(e?.message || 'Failed to update resource cleanup setting');
    } finally {
      setResourceBusy('');
    }
  }, [draft, applyUpdatedDraft, onError]);

  const handleCreateTrackedNetwork = useCallback(async () => {
    if (!draft || !newRealNetName.trim() || !newRealNetSite) return;
    setResourceBusy('create-network');
    try {
      const net = await api.createChameleonNetwork({
        site: newRealNetSite,
        name: newRealNetName.trim(),
        cidr: newRealNetCidr.trim() || undefined,
      });
      const updated = await api.addChameleonSliceResource(draft.id, {
        type: 'network',
        id: net.id,
        name: net.name,
        site: net.site,
        status: net.status,
        cidr: networkCidrs(net),
        ownership: 'managed',
        managed: true,
        delete_with_slice: true,
      });
      applyUpdatedDraft(updated);
      setNewRealNetName('');
      setNewRealNetCidr('');
      await refreshResourceInventory();
    } catch (e: any) {
      onError?.(e?.message || 'Failed to create network');
    } finally {
      setResourceBusy('');
    }
  }, [draft, newRealNetName, newRealNetSite, newRealNetCidr, applyUpdatedDraft, refreshResourceInventory, onError]);

  const handleAttachExistingNetworkResource = useCallback(async () => {
    if (!draft || !selectedExistingNetResource) return;
    const net = existingNetworks.find(n => n.id === selectedExistingNetResource);
    if (!net) return;
    setResourceBusy(`network:${net.id}`);
    try {
      const updated = await api.addChameleonSliceResource(draft.id, {
        type: 'network',
        id: net.id,
        name: net.name,
        site: net.site,
        status: net.status,
        cidr: networkCidrs(net),
        ownership: 'imported',
        managed: false,
        delete_with_slice: false,
      });
      applyUpdatedDraft(updated);
      setSelectedExistingNetResource('');
    } catch (e: any) {
      onError?.(e?.message || 'Failed to attach network');
    } finally {
      setResourceBusy('');
    }
  }, [draft, selectedExistingNetResource, existingNetworks, applyUpdatedDraft, onError]);

  const handleAllocateTrackedFloatingIp = useCallback(async () => {
    if (!draft || !allocFipSite) return;
    setResourceBusy('allocate-fip');
    try {
      const fip = await api.allocateChameleonFloatingIp(allocFipSite);
      const updated = await api.addChameleonSliceResource(draft.id, {
        type: 'floating_ip',
        id: fip.id,
        name: fip.floating_ip_address || fip.id,
        site: fip._site || allocFipSite,
        status: fip.status,
        floating_ip: fip.floating_ip_address,
        floating_ip_id: fip.id,
        port_id: fip.port_id || '',
        ownership: 'managed',
        managed: true,
        delete_with_slice: true,
      });
      applyUpdatedDraft(updated, { refresh: false });
      await refreshResourceInventory();
    } catch (e: any) {
      onError?.(e?.message || 'Failed to allocate floating IP');
    } finally {
      setResourceBusy('');
    }
  }, [draft, allocFipSite, applyUpdatedDraft, refreshResourceInventory, onError]);

  const handleAttachFloatingIpResource = useCallback(async () => {
    if (!draft || !selectedFipId) return;
    const fip = floatingIps.find(ip => ip.id === selectedFipId);
    if (!fip) return;
    setResourceBusy(`fip:${selectedFipId}`);
    try {
      const site = resourceSite(fip, allocFipSite || draftSites[0] || 'CHI@TACC');
      const associated = selectedFipTargetPort
        ? await api.associateChameleonFloatingIp(fip.id, site, selectedFipTargetPort)
        : fip;
      const updated = await api.addChameleonSliceResource(draft.id, {
        type: 'floating_ip',
        id: fip.id,
        name: associated.floating_ip_address || fip.floating_ip_address || fip.id,
        site,
        status: associated.status || fip.status,
        floating_ip: associated.floating_ip_address || fip.floating_ip_address,
        floating_ip_id: fip.id,
        port_id: associated.port_id || selectedFipTargetPort || fip.port_id || '',
        ownership: 'imported',
        managed: false,
        delete_with_slice: false,
      });
      applyUpdatedDraft(updated, { refresh: false });
      setSelectedFipId('');
      setSelectedFipTargetPort('');
      await refreshResourceInventory();
    } catch (e: any) {
      onError?.(e?.message || 'Failed to attach floating IP');
    } finally {
      setResourceBusy('');
    }
  }, [draft, selectedFipId, selectedFipTargetPort, floatingIps, allocFipSite, draftSites, applyUpdatedDraft, refreshResourceInventory, onError]);

  const handleAttachSecurityGroupResource = useCallback(async (sg: any) => {
    if (!draft) return;
    const id = sg.id || '';
    if (!id) return;
    setResourceBusy(`sg:${id}`);
    try {
      const updated = await api.addChameleonSliceResource(draft.id, {
        type: 'security_group',
        id,
        name: sg.name || id,
        site: resourceSite(sg, draftSites[0] || 'CHI@TACC'),
        status: '',
        ownership: 'imported',
        managed: false,
        delete_with_slice: false,
      });
      applyUpdatedDraft(updated, { refresh: false });
    } catch (e: any) {
      onError?.(e?.message || 'Failed to attach security group');
    } finally {
      setResourceBusy('');
    }
  }, [draft, draftSites, applyUpdatedDraft, onError]);

  const renderInterfaceControls = (n: any) => {
    const siteNets = existingNetworks.filter(net => net.site === (n.site || draft?.site));
    const ifaces = (n as any).interfaces || [{ nic: 0, network: (n as any).network || null }, { nic: 1, network: null }];
    return ifaces.map((ifc: any, ifcIdx: number) => (
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
            const updated_ifaces = ifaces.map((f: any, i: number) => i === ifcIdx ? { ...f, network } : f);
            try {
              const updated = await api.updateChameleonNodeInterfaces(draft.id, n.id, updated_ifaces);
              applyUpdatedDraft(updated);
            } catch (err: any) {
              onError?.(err?.message || 'Failed to update interface');
            }
          }}
        >
          <option value="">-- Unconnected --</option>
          {siteNets.map(sn => (
            <option key={sn.id} value={sn.id}>
              {sn.name}{sn.shared ? ' (shared)' : ''}{networkCidrs(sn) ? ` [${networkCidrs(sn)}]` : ''}
            </option>
          ))}
        </select>
      </div>
    ));
  };

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
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }} data-testid="chameleon-editor">
        {(!draft || state === 'empty') ? (
          <div style={{ padding: 16, textAlign: 'center', color: 'var(--fabric-text-muted)', fontSize: 12 }}>
            Select or create a draft from the Chameleon bar to start editing.
          </div>
        ) : (
          <>
            <div className="editor-top-tabs" data-testid="chameleon-editor-tabs">
              <button className={chiEditorTab === 'leases' ? 'active chameleon-tab-active' : ''} onClick={() => setChiEditorTab('leases')} data-testid="chameleon-editor-tab" data-chameleon-tab="leases">Leases</button>
              <button className={chiEditorTab === 'servers' ? 'active chameleon-tab-active' : ''} onClick={() => setChiEditorTab('servers')} data-testid="chameleon-editor-tab" data-chameleon-tab="servers">Servers</button>
              <button className={chiEditorTab === 'networks' ? 'active chameleon-tab-active' : ''} onClick={() => setChiEditorTab('networks')} data-testid="chameleon-editor-tab" data-chameleon-tab="networks">Networks</button>
              <button className={chiEditorTab === 'ips' ? 'active chameleon-tab-active' : ''} onClick={() => setChiEditorTab('ips')} data-testid="chameleon-editor-tab" data-chameleon-tab="ips">IPs</button>
              <button className={chiEditorTab === 'resources' ? 'active chameleon-tab-active' : ''} onClick={() => setChiEditorTab('resources')} data-testid="chameleon-editor-tab" data-chameleon-tab="resources">Resources</button>
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
                  <FilterBox
                    value={leaseFilter}
                    onChange={setLeaseFilter}
                    placeholder="Search leases by name, site, status, ID..."
                    resultCount={filteredLeaseResources.length + filteredAvailableLeases.length}
                    totalCount={leaseResources.length + availableLeases.length}
                    testId="chameleon-lease-filter"
                  />

                  {/* Pre-submit configuration */}
                  {draft.state === 'Draft' && draft.nodes.length > 0 && (
                    <div style={{ borderTop: '1px solid var(--fabric-border)', paddingTop: 8, marginBottom: 8 }}>
                      <h5 style={{ fontSize: 11, fontWeight: 700, margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--fabric-text-muted)' }}>Reservation</h5>

                      {/* Lease mode toggle */}
                      <div style={{ display: 'flex', gap: 8, marginBottom: 8, fontSize: 11 }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                          <input
                            type="radio"
                            name="leaseMode"
                            value="new"
                            checked={leaseMode === 'new'}
                            onChange={() => setLeaseMode('new')}
                            style={{ accentColor: '#39B54A' }}
                          />
                          Create new lease
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                          <input
                            type="radio"
                            name="leaseMode"
                            value="existing"
                            checked={leaseMode === 'existing'}
                            onChange={() => setLeaseMode('existing')}
                            style={{ accentColor: '#39B54A' }}
                          />
                          Use existing lease
                        </label>
                      </div>

                      {leaseMode === 'new' ? (
                        <>
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
                          <div style={{ fontSize: 10, color: 'var(--fabric-text-muted)', marginBottom: 6 }}>
                            {draft.nodes.length} server{draft.nodes.length !== 1 ? 's' : ''} across {draftSites.length} site{draftSites.length !== 1 ? 's' : ''} will be reserved.
                          </div>
                          <button
                            className="chi-editor-deploy-btn"
                            style={{ width: '100%', fontSize: 11, padding: '6px 8px', marginBottom: 4 }}
                            disabled={precreating || draft.nodes.length === 0}
                            onClick={handlePrecreateLease}
                            title="Create the Chameleon lease now (separately from slice deployment). The lease will be selected for use when you click Submit."
                          >
                            {precreating ? 'Creating lease...' : 'Pre-create lease for slice'}
                          </button>
                          {precreateStatus && (
                            <div style={{ fontSize: 10, color: 'var(--fabric-text-muted)', marginBottom: 4 }}>
                              {precreateStatus}
                            </div>
                          )}
                        </>
                      ) : (
                        <>
                          <div style={{ fontSize: 10, color: 'var(--fabric-text-muted)', marginBottom: 6 }}>
                            Pick an existing lease for each site:
                          </div>
                          {draftSites.length === 0 && (
                            <div style={{ fontSize: 11, color: 'var(--fabric-coral)', marginBottom: 4 }}>
                              No sites in draft. Add servers first.
                            </div>
                          )}
                          {draftSites.map(site => {
                            const siteLeases = availableLeases.filter(l =>
                              (l.site || l._site || '') === site && (l.status === 'ACTIVE' || l.status === 'PENDING' || l.status === 'STARTING')
                            );
                            return (
                              <div key={site} style={{ marginBottom: 6 }}>
                                <label style={{ display: 'block', fontSize: 10, fontWeight: 600, color: 'var(--fabric-text-muted)', marginBottom: 2 }}>
                                  {site}
                                </label>
                                <select
                                  className="chi-form-input"
                                  value={selectedExistingLeases[site] || ''}
                                  onChange={e => setSelectedExistingLeases(prev => ({ ...prev, [site]: e.target.value }))}
                                  style={{ width: '100%', fontSize: 11 }}
                                >
                                  <option value="">— select a lease —</option>
                                  {siteLeases.map(lease => (
                                    <option key={lease.id} value={lease.id}>
                                      {lease.name} ({lease.status})
                                    </option>
                                  ))}
                                </select>
                                {siteLeases.length === 0 && !loadingLeases && (
                                  <div style={{ fontSize: 9, color: 'var(--fabric-text-muted)', marginTop: 2 }}>
                                    No active leases at {site}. Switch to "Create new lease".
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </>
                      )}
                      <div style={{ fontSize: 10, color: 'var(--fabric-text-muted)', marginTop: 4 }}>
                        Click <strong>Submit</strong> in the toolbar to deploy.
                      </div>
                    </div>
                  )}

                  {/* Existing lease management */}
                  {leaseResources.length === 0 ? (
                    draft.state !== 'Draft' ? (
                      <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', padding: '8px 0', borderTop: '1px solid var(--fabric-border)' }}>
                        No active leases.
                      </div>
                    ) : null
                  ) : (
                    <>
                      <div style={{ borderTop: '1px solid var(--fabric-border)', paddingTop: 8 }}>
                        <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 6px' }}>
                          Leases ({filteredLeaseResources.length}/{leaseResources.length})
                        </h5>
                      </div>
                      {filteredLeaseResources.map(lease => (
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
                          <div style={{ display: 'flex', gap: 4 }}>
                            <button
                              className="chi-action-btn"
                              style={{ fontSize: 10, flex: 1 }}
                              disabled={resourceBusy === lease.resource_id}
                              onClick={() => confirmEditorAction({
                                title: 'Detach Lease From Slice',
                                message: `Detach lease "${lease.name}" from this Chameleon slice? The lease will remain in Chameleon.`,
                                details: leaseDetachDetails(lease),
                                confirmLabel: 'Detach from slice',
                                onConfirm: () => detachSliceResource(lease),
                              })}
                            >
                              Detach from slice
                            </button>
                            <button
                              className="chi-action-btn chi-action-btn-danger"
                              style={{ fontSize: 10, flex: 1 }}
                              disabled={deletingLease === lease.resource_id || resourceBusy === lease.resource_id}
                              onClick={() => confirmEditorAction({
                                title: 'Delete Lease From Chameleon',
                                message: `Delete lease "${lease.name}" from Chameleon and detach it from this slice? This cannot be undone.`,
                                details: leaseDetachDetails(lease),
                                danger: true,
                                confirmLabel: 'Delete from Chameleon',
                                onConfirm: async () => {
                                  setDeletingLease(lease.resource_id);
                                  try {
                                    await deleteSliceResource(lease);
                                  } finally {
                                    setDeletingLease('');
                                  }
                                },
                              })}
                            >
                              {deletingLease === lease.resource_id ? 'Deleting...' : 'Delete lease'}
                            </button>
                          </div>
                        </div>
                      ))}
                    </>
                  )}

                  {/* Available leases checklist */}
                  <div style={{ borderTop: '1px solid var(--fabric-border)', paddingTop: 8, marginTop: 8 }}>
                    <h5 style={{ fontSize: 11, fontWeight: 700, margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--fabric-text-muted)' }}>
                      Available Leases {loadingLeases && '...'}
                    </h5>
                    {filteredAvailableLeases.length === 0 && !loadingLeases ? (
                      <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', padding: '4px 0' }}>
                        {availableLeases.length === 0 ? `No leases found at ${draftSites.join(', ') || 'any site'}.` : 'No leases match the current search.'}
                      </div>
                    ) : (
                      filteredAvailableLeases.map(lease => {
                        const leaseSite = lease.site || lease._site || '';
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
                                    await api.importChameleonReservation(draft.id, leaseSite, lease.id, { include_lease: true });
                                    updated = await api.getChameleonDraft(draft.id);
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
                                {leaseSite && <span>@ {leaseSite}</span>}
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
                  <select className="chi-form-input" value={nodeSite} onChange={e => { setNodeSite(e.target.value); setNodeType(''); setNodeImage(''); setNodeKeyName(''); }} style={{ marginBottom: 4, fontSize: 11 }} data-testid="chameleon-server-site-select">
                    {configuredSites.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
                  </select>
                  <ChameleonNodeTypeComboBox nodeTypes={nodeTypes} value={nodeType} onSelect={setNodeType} disabled={loadingData} compact />
                  <div style={{ marginTop: 4 }}>
                    <ChameleonImageComboBox images={images} value={nodeImage} onSelect={setNodeImage} disabled={loadingData} compact />
                  </div>
                  <select
                    className="chi-form-input"
                    value={nodeKeyName}
                    onChange={e => setNodeKeyName(e.target.value)}
                    style={{ marginTop: 4, fontSize: 11 }}
                    data-testid="chameleon-server-key-select"
                    disabled={!!loadingKeypairsBySite[effectiveSite]}
                  >
                    <option value="">Use site default SSH key</option>
                    {getKeypairNamesForSite(effectiveSite, nodeKeyName).map(keyName => (
                      <option key={keyName} value={keyName}>{keyName}</option>
                    ))}
                  </select>
                  <button className="chi-editor-deploy-btn" disabled={!nodeType || !nodeImage || addingNode} onClick={handleAddNode} style={{ marginTop: 4 }} data-testid="chameleon-add-server">
                    {addingNode ? 'Adding...' : '+ Add Server'}
                  </button>
                  <div style={{ marginTop: 10 }}>
                    <FilterBox
                      value={serverFilter}
                      onChange={setServerFilter}
                      placeholder="Search servers by name, site, type, status, IP..."
                      resultCount={filteredPlannedNodes.length + filteredInstanceResources.length + filteredUnaffiliatedInstances.length}
                      totalCount={draft.nodes.length + instanceResources.length + unaffiliatedInstances.length}
                      testId="chameleon-server-filter"
                    />
                  </div>
                  {draft.nodes.length > 0 ? (
                    <div style={{ marginTop: 12 }}>
                      <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 4px' }}>Planned Servers ({filteredPlannedNodes.length}/{draft.nodes.length})</h5>
                      {filteredPlannedNodes.length === 0 ? (
                        <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', marginTop: 8 }}>No planned servers match the current search.</div>
                      ) : filteredPlannedNodes.map(n => {
                        const siteNets = existingNetworks.filter(net => net.site === (n.site || draft.site));
                        return (
                          <div
                            key={n.id}
                            className="chi-editor-item"
                            style={{ flexDirection: 'column', alignItems: 'stretch', gap: 4 }}
                            data-testid="chameleon-planned-server-row"
                            data-node-id={n.id}
                            data-node-name={n.name}
                            data-site={n.site || ''}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <span style={{ fontWeight: 600, flex: 1 }}>{n.name}</span>
                              <span style={{ fontSize: 10, color: 'var(--fabric-text-muted)' }}>{n.node_type}</span>
                              <span style={{ fontSize: 9, color: 'var(--fabric-text-muted)' }}>
                                key: {n.key_name || 'site default'}
                              </span>
                              {n.site && <span style={{ fontSize: 9, color: 'var(--fabric-success, #39B54A)' }}>@{n.site}</span>}
                              <button
                                className="chi-editor-item-remove"
                                style={{ color: 'var(--fabric-primary, #5798bc)', fontSize: 12 }}
                                title="Edit this server"
                                onClick={() => editingNodeId === n.id ? cancelEditNode() : startEditNode(n)}
                              >
                                {editingNodeId === n.id ? '\u2715' : '\u270E'}
                              </button>
                              <button className="chi-editor-item-remove" title="Delete this server" onClick={() => handleRemoveNode(n.id)}>×</button>
                            </div>
                            {editingNodeId === n.id && (
                              <div style={{ borderTop: '1px solid var(--fabric-border)', paddingTop: 6, marginTop: 4 }}>
                                <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--fabric-text-muted)', marginBottom: 4 }}>Edit Server</div>
                                <input
                                  className="chi-form-input"
                                  type="text"
                                  placeholder="Name"
                                  value={editNodeName}
                                  onChange={e => setEditNodeName(e.target.value)}
                                  style={{ marginBottom: 4, fontSize: 11, width: '100%' }}
                                />
                                <ChameleonNodeTypeComboBox
                                  nodeTypes={nodeTypes}
                                  value={editNodeType}
                                  onSelect={setEditNodeType}
                                  disabled={loadingData || savingNodeEdit}
                                  compact
                                />
                                <div style={{ marginTop: 4 }}>
                                  <ChameleonImageComboBox
                                    images={images}
                                    value={editNodeImage}
                                    onSelect={setEditNodeImage}
                                    disabled={loadingData || savingNodeEdit}
                                    compact
                                  />
                                </div>
                                <select
                                  className="chi-form-input"
                                  value={editNodeKeyName}
                                  onChange={e => setEditNodeKeyName(e.target.value)}
                                  style={{ marginTop: 4, fontSize: 11, width: '100%' }}
                                  data-testid="chameleon-server-edit-key-select"
                                  disabled={savingNodeEdit || !!loadingKeypairsBySite[n.site || draft.site || effectiveSite]}
                                >
                                  <option value="">Use site default SSH key</option>
                                  {getKeypairNamesForSite(n.site || draft.site || effectiveSite, editNodeKeyName).map(keyName => (
                                    <option key={keyName} value={keyName}>{keyName}</option>
                                  ))}
                                </select>
                                <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
                                  <button
                                    className="chi-editor-deploy-btn"
                                    style={{ flex: 1, fontSize: 11 }}
                                    disabled={savingNodeEdit || !editNodeType || !editNodeImage}
                                    onClick={saveNodeEdit}
                                  >
                                    {savingNodeEdit ? 'Saving...' : 'Save'}
                                  </button>
                                  <button
                                    className="chi-editor-deploy-btn"
                                    style={{ fontSize: 11, background: 'var(--fabric-text-muted)' }}
                                    disabled={savingNodeEdit}
                                    onClick={cancelEditNode}
                                  >
                                    Cancel
                                  </button>
                                </div>
                              </div>
                            )}
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
                  {instanceResources.length > 0 && (
                    <div style={{ marginTop: 12, borderTop: '1px solid var(--fabric-border)', paddingTop: 8 }}>
                      <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 4px' }}>Live / Imported Servers ({filteredInstanceResources.length}/{instanceResources.length})</h5>
                      <CompactResourceTable
                        items={filteredInstanceResources}
                        getKey={(resource) => resource.resource_id || resourceProviderId(resource)}
                        emptyLabel="No live or imported servers match the current search."
                        testId="chameleon-live-server-table"
                        getRowTestId={() => 'chameleon-live-server-row'}
                        getRowAttributes={(resource) => ({
                          'data-resource-id': resource.resource_id,
                          'data-provider-id': resourceProviderId(resource),
                          'data-resource-name': resourceDisplayName(resource),
                          'data-site': resourceSite(resource),
                        })}
                        columns={[
                          { key: 'name', label: 'Name', render: (resource) => resource.name || shortId(resourceProviderId(resource)) },
                          { key: 'site', label: 'Site', width: '82px', render: (resource) => resourceSite(resource) },
                          {
                            key: 'status',
                            label: 'Status',
                            width: '70px',
                            render: (resource) => (
                              <span className={`chi-status ${statusClass(resource.status || 'UNKNOWN')}`} style={{ fontSize: 9 }}>
                                {resource.status || 'UNKNOWN'}
                              </span>
                            ),
                          },
                          {
                            key: 'ip',
                            label: 'IP',
                            render: (resource) => resource.floating_ip || resource.management_ip || (resource.ip_addresses || [])[0] || '-',
                          },
                          { key: 'owner', label: 'Owner', width: '62px', render: (resource) => resource.ownership || 'managed' },
                          {
                            key: 'actions',
                            label: 'Actions',
                            render: (resource) => {
                              const id = resourceProviderId(resource);
                              const site = resourceSite(resource);
                              const fip = resource.floating_ip || '';
                              const busy = resourceBusy === (resource.resource_id || id);
                              return (
                                <InlineActions>
                                  {onOpenTerminal && id && fip && resource.status === 'ACTIVE' && (
                                    <button className="chi-editor-deploy-btn" style={{ fontSize: 10, padding: '2px 8px' }} onClick={() => onOpenTerminal?.({ id, name: resource.name || id, site })}>
                                      Terminal
                                    </button>
                                  )}
                                  <button className="chi-action-btn" style={{ fontSize: 10 }} onClick={() => setChiEditorTab('ips')}>
                                    Manage IP
                                  </button>
                                  <button
                                    className="chi-action-btn"
                                    style={{ fontSize: 10 }}
                                    disabled={busy}
                                    onClick={() => confirmEditorAction({
                                      title: 'Detach Server From Slice',
                                      message: `Detach server "${resource.name || id}" from this slice? The Chameleon instance will keep running.`,
                                      confirmLabel: 'Detach from slice',
                                      onConfirm: () => detachSliceResource(resource),
                                    })}
                                  >
                                    Detach from slice
                                  </button>
                                  <button
                                    className="chi-action-btn chi-action-btn-danger"
                                    style={{ fontSize: 10 }}
                                    disabled={busy}
                                    onClick={() => confirmEditorAction({
                                      title: 'Delete Server From Chameleon',
                                      message: `Delete server "${resource.name || id}" from Chameleon and detach it from this slice? This cannot be undone.`,
                                      danger: true,
                                      confirmLabel: 'Delete from Chameleon',
                                      onConfirm: () => deleteSliceResource(resource),
                                    })}
                                  >
                                    Delete from Chameleon
                                  </button>
                                </InlineActions>
                              );
                            },
                          },
                        ]}
                      />
                    </div>
                  )}
                  {/* Add Existing Server */}
                  {draft && (
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
                        {loadingUnaffiliated ? 'Searching...' : 'Find Unattached Project Servers'}
                      </button>
                      {unaffiliatedInstances.length > 0 && (
                        <CompactResourceTable
                          items={filteredUnaffiliatedInstances}
                          getKey={(inst) => inst.id}
                          emptyLabel="No unattached servers match the current search."
                          testId="chameleon-unattached-server-table"
                          getRowTestId={() => 'chameleon-unattached-server-row'}
                          getRowAttributes={(inst) => ({
                            'data-provider-id': inst.id,
                            'data-resource-name': inst.name,
                            'data-site': inst.site,
                          })}
                          columns={[
                            { key: 'name', label: 'Name', render: (inst) => inst.name || shortId(inst.id) },
                            { key: 'site', label: 'Site', width: '82px', render: (inst) => inst.site || '-' },
                            {
                              key: 'status',
                              label: 'Status',
                              width: '70px',
                              render: (inst) => <span className={`chi-status ${statusClass(inst.status || 'UNKNOWN')}`} style={{ fontSize: 9 }}>{inst.status || 'UNKNOWN'}</span>,
                            },
                            { key: 'ip', label: 'IP', render: (inst) => inst.floating_ip || (inst.ip_addresses || [])[0] || '-' },
                            {
                              key: 'action',
                              label: 'Action',
                              width: '92px',
                              render: (inst) => (
                                <button
                                  className="chi-editor-deploy-btn"
                                  style={{ fontSize: 11, padding: '2px 8px' }}
                                  disabled={addingExistingServer}
                                  onClick={async () => {
                                    if (!draft) return;
                                    setAddingExistingServer(true);
                                    setSelectedUnaffiliated(inst.id);
                                    try {
                                      const updated = await api.addChameleonSliceResource(draft.id, {
                                        type: 'instance',
                                        id: inst.id,
                                        name: inst?.name || 'server',
                                        site: inst?.site || '',
                                        status: inst?.status,
                                        image: inst?.image,
                                        ip_addresses: inst?.ip_addresses,
                                        floating_ip: inst?.floating_ip,
                                        port_id: inst?.port_id,
                                        ownership: 'imported',
                                        managed: false,
                                        delete_with_slice: false,
                                      });
                                      applyUpdatedDraft(updated);
                                      setSelectedUnaffiliated('');
                                      setUnaffiliatedInstances(prev => prev.filter(i => i.id !== inst.id));
                                    } catch (e: any) {
                                      onError?.(e.message || 'Failed to add server to slice');
                                    } finally {
                                      setAddingExistingServer(false);
                                    }
                                  }}
                                >
                                  {addingExistingServer && selectedUnaffiliated === inst.id ? 'Adding...' : 'Attach'}
                                </button>
                              ),
                            },
                          ]}
                        />
                      )}
                    </div>
                  )}
                </div>
              )}
              {chiEditorTab === 'networks' && (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                    <h5 style={{ fontSize: 11, fontWeight: 600, margin: 0 }}>Create Chameleon Network</h5>
                    <button className="chi-action-btn" style={{ fontSize: 10 }} onClick={() => refreshResourceInventory()} disabled={loadingInventory}>
                      {loadingInventory ? 'Refreshing...' : 'Refresh'}
                    </button>
                  </div>
                  <FilterBox
                    value={networkFilter}
                    onChange={setNetworkFilter}
                    placeholder="Search networks by name, site, CIDR, status..."
                    resultCount={filteredExistingNetworkResources.length + filteredNetworkResources.length + filteredDraftNetworks.length}
                    totalCount={existingNetworks.filter(n => !trackedNetworkIds.has(n.id)).length + networkResources.length + draft.networks.length}
                    testId="chameleon-network-filter"
                  />
                  <input className="chi-form-input" value={newRealNetName} onChange={e => setNewRealNetName(e.target.value)} placeholder="Network name" style={{ marginBottom: 4 }} />
                  <select className="chi-form-input" value={newRealNetSite} onChange={e => setNewRealNetSite(e.target.value)} style={{ marginBottom: 4, fontSize: 11 }}>
                    {configuredSites.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
                  </select>
                  <input className="chi-form-input" value={newRealNetCidr} onChange={e => setNewRealNetCidr(e.target.value)} placeholder="Optional CIDR, e.g. 192.168.100.0/24" style={{ marginBottom: 4 }} />
                  <button className="chi-editor-deploy-btn" disabled={!newRealNetName.trim() || !newRealNetSite || resourceBusy === 'create-network'} onClick={handleCreateTrackedNetwork}>
                    {resourceBusy === 'create-network' ? 'Creating...' : 'Create and track network'}
                  </button>

                  <div style={{ borderBottom: '1px solid var(--fabric-border)', margin: '12px 0' }} />
                  <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 6px' }}>Attach Existing Network</h5>
                  <select className="chi-form-input" value={selectedExistingNetResource} onChange={e => setSelectedExistingNetResource(e.target.value)}>
                    <option value="">-- Select Network --</option>
                    {filteredExistingNetworkResources.map(n => (
                      <option key={n.id} value={n.id}>
                        {n.name}{n.shared ? ' (shared)' : ''}{networkCidrs(n) ? ` - ${networkCidrs(n)}` : ''} @ {n.site}
                      </option>
                    ))}
                  </select>
                  <button className="chi-editor-deploy-btn" disabled={!selectedExistingNetResource || resourceBusy.startsWith('network:')} onClick={handleAttachExistingNetworkResource} style={{ marginTop: 4 }}>
                    Attach to slice
                  </button>

                  <div style={{ borderBottom: '1px solid var(--fabric-border)', margin: '12px 0' }} />
                  <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 6px' }}>Plan Draft Network</h5>
                  <input className="chi-form-input" value={netName} onChange={e => setNetName(e.target.value)} placeholder="Draft network name" data-testid="chameleon-draft-network-name" />
                  {draft.nodes.length > 0 && (
                    <>
                      <label style={{ fontSize: 10, fontWeight: 600, display: 'block', marginTop: 6, marginBottom: 2 }}>Connect Nodes:</label>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {draft.nodes.map(n => (
                          <label key={n.id} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, cursor: 'pointer' }} data-testid="chameleon-draft-network-node-option" data-node-id={n.id} data-node-name={n.name}>
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
                  <button className="chi-editor-deploy-btn" disabled={!netName || addingNet} onClick={handleAddNetwork} style={{ marginTop: 4 }} data-testid="chameleon-add-draft-network">
                    {addingNet ? 'Adding...' : '+ Add draft network'}
                  </button>

                  {draft.nodes.length > 0 && (
                    <div style={{ marginTop: 12, borderTop: '1px solid var(--fabric-border)', paddingTop: 8 }}>
                      <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 4px' }}>NIC Connections</h5>
                      {draft.nodes.map(n => (
                        <div
                          key={n.id}
                          className="chi-editor-item"
                          style={{ flexDirection: 'column', alignItems: 'stretch', gap: 4 }}
                          data-testid="chameleon-nic-row"
                          data-node-id={n.id}
                          data-node-name={n.name}
                          data-site={n.site}
                        >
                          <div style={{ fontWeight: 600, fontSize: 11 }}>{n.name} <span style={{ color: 'var(--fabric-text-muted)', fontWeight: 400 }}>@ {n.site}</span></div>
                          {renderInterfaceControls(n)}
                        </div>
                      ))}
                    </div>
                  )}

                  {networkResources.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 4px' }}>Tracked Chameleon Networks ({filteredNetworkResources.length}/{networkResources.length})</h5>
                      <CompactResourceTable
                        items={filteredNetworkResources}
                        getKey={(resource) => resource.resource_id || resourceProviderId(resource)}
                        emptyLabel="No tracked networks match the current search."
                        testId="chameleon-tracked-network-table"
                        getRowTestId={() => 'chameleon-tracked-network-row'}
                        getRowAttributes={(resource) => ({
                          'data-resource-id': resource.resource_id,
                          'data-provider-id': resourceProviderId(resource),
                          'data-resource-name': resourceDisplayName(resource),
                          'data-site': resourceSite(resource),
                        })}
                        columns={[
                          { key: 'name', label: 'Name', render: (resource) => resource.name || shortId(resourceProviderId(resource)) },
                          { key: 'site', label: 'Site', width: '82px', render: (resource) => resourceSite(resource) },
                          { key: 'cidr', label: 'CIDR', render: (resource) => resource.cidr || '-' },
                          { key: 'owner', label: 'Owner', width: '62px', render: (resource) => resource.ownership || 'managed' },
                          {
                            key: 'actions',
                            label: 'Actions',
                            render: (resource) => {
                              const id = resourceProviderId(resource);
                              const busy = resourceBusy === (resource.resource_id || id);
                              return (
                                <InlineActions>
                                  <button className="chi-action-btn" style={{ fontSize: 10 }} disabled={busy} onClick={() => confirmEditorAction({
                                    title: 'Detach Network From Slice',
                                    message: `Detach network "${resource.name || id}" from this slice? The Neutron network will remain in Chameleon.`,
                                    confirmLabel: 'Detach from slice',
                                    onConfirm: () => detachSliceResource(resource),
                                  })}>Detach from slice</button>
                                  <button className="chi-action-btn chi-action-btn-danger" style={{ fontSize: 10 }} disabled={busy} onClick={() => confirmEditorAction({
                                    title: 'Delete Network From Chameleon',
                                    message: `Delete network "${resource.name || id}" from Chameleon and detach it from this slice? This can affect attached ports.`,
                                    details: ['Any server NIC using this network may lose connectivity.'],
                                    danger: true,
                                    confirmLabel: 'Delete from Chameleon',
                                    onConfirm: () => deleteSliceResource(resource),
                                  })}>Delete from Chameleon</button>
                                </InlineActions>
                              );
                            },
                          },
                        ]}
                      />
                    </div>
                  )}

                  {draft.networks.length > 0 ? (
                    <div style={{ marginTop: 12 }}>
                      <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 4px' }}>Draft Networks ({filteredDraftNetworks.length}/{draft.networks.length})</h5>
                      <CompactResourceTable
                        items={filteredDraftNetworks}
                        getKey={(network) => network.id}
                        emptyLabel="No draft networks match the current search."
                        testId="chameleon-draft-network-table"
                        getRowTestId={() => 'chameleon-draft-network-row'}
                        getRowAttributes={(network) => ({
                          'data-network-id': network.id,
                          'data-network-name': network.name,
                        })}
                        columns={[
                          { key: 'name', label: 'Name', render: (network) => network.name },
                          {
                            key: 'members',
                            label: 'Connected',
                            render: (network) => `${(network.connected_nodes || []).length} server${(network.connected_nodes || []).length === 1 ? '' : 's'}`,
                          },
                          {
                            key: 'actions',
                            label: 'Actions',
                            width: '86px',
                            render: (network) => (
                              <button className="chi-action-btn chi-action-btn-danger" style={{ fontSize: 10 }} title="Remove from draft" onClick={() => handleRemoveNetwork(network.id)}>
                                Remove from draft
                              </button>
                            ),
                          },
                        ]}
                      />
                    </div>
                  ) : (
                    <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', marginTop: 8 }}>No draft networks yet.</div>
                  )}
                </div>
              )}
              {chiEditorTab === 'ips' && (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                    <h5 style={{ fontSize: 11, fontWeight: 600, margin: 0 }}>Floating IP Intent</h5>
                    <button className="chi-action-btn" style={{ fontSize: 10 }} onClick={() => refreshResourceInventory()} disabled={loadingInventory}>
                      {loadingInventory ? 'Refreshing...' : 'Refresh'}
                    </button>
                  </div>
                  <FilterBox
                    value={ipFilter}
                    onChange={setIpFilter}
                    placeholder="Search IPs by address, node, site, status, port..."
                    resultCount={filteredIpIntentNodes.length + filteredFloatingIps.length + filteredFloatingIpResources.length}
                    totalCount={draft.nodes.length + floatingIps.filter(ip => !trackedFloatingIpIds.has(ip.id)).length + floatingIpResources.length}
                    testId="chameleon-ip-filter"
                  />
                  {draft.nodes.length > 0 ? filteredIpIntentNodes.map(n => (
                    <div
                      key={n.id}
                      className="chi-editor-item"
                      style={{ flexDirection: 'column', alignItems: 'stretch', gap: 4 }}
                      data-testid="chameleon-floating-ip-intent-row"
                      data-node-id={n.id}
                      data-node-name={n.name}
                    >
                      <div style={{ fontWeight: 600, fontSize: 11 }}>{n.name}</div>
                      <select
                        value={fipHasNode(draft.floating_ips || [], n.id) ? String(fipGetNic(draft.floating_ips || [], n.id)) : 'none'}
                        onChange={async (e) => {
                          const val = e.target.value;
                          const newFips = val === 'none'
                            ? fipRemove(draft.floating_ips || [], n.id)
                            : fipAdd(draft.floating_ips || [], n.id, parseInt(val));
                          try {
                            const updated = await api.setDraftFloatingIps(draft.id, newFips);
                            applyUpdatedDraft(updated, { refresh: false });
                          } catch (err: any) {
                            onError?.(err?.message || 'Failed to update floating IP intent');
                          }
                        }}
                        style={{ fontSize: 10, padding: '2px 4px', borderRadius: 3, border: '1px solid var(--fabric-border)' }}
                      >
                        <option value="none">No floating IP on deploy</option>
                        {(n.interfaces || []).map((ifc: any, idx: number) => (
                          <option key={idx} value={String(ifc.nic ?? idx)}>NIC {ifc.nic ?? idx}{ifc.network ? ` (${ifc.network.name})` : ''}</option>
                        ))}
                      </select>
                    </div>
                  )) : (
                    <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)' }}>Add planned servers before setting deploy-time floating IP intent.</div>
                  )}

                  <div style={{ borderBottom: '1px solid var(--fabric-border)', margin: '12px 0' }} />
                  <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 6px' }}>Allocate Floating IP</h5>
                  <select className="chi-form-input" value={allocFipSite} onChange={e => setAllocFipSite(e.target.value)} style={{ marginBottom: 4, fontSize: 11 }}>
                    {configuredSites.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
                  </select>
                  <button className="chi-editor-deploy-btn" disabled={!allocFipSite || resourceBusy === 'allocate-fip'} onClick={handleAllocateTrackedFloatingIp}>
                    {resourceBusy === 'allocate-fip' ? 'Allocating...' : 'Allocate and track IP'}
                  </button>

                  <div style={{ borderBottom: '1px solid var(--fabric-border)', margin: '12px 0' }} />
                  <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 6px' }}>Attach Existing Floating IP</h5>
                  <select className="chi-form-input" value={selectedFipId} onChange={e => setSelectedFipId(e.target.value)} style={{ marginBottom: 4 }}>
                    <option value="">-- Select floating IP --</option>
                    {filteredFloatingIps.map(ip => (
                      <option key={ip.id} value={ip.id}>{ip.floating_ip_address || ip.id} ({ip.status || 'UNKNOWN'}) @ {resourceSite(ip, '')}</option>
                    ))}
                  </select>
                  <select className="chi-form-input" value={selectedFipTargetPort} onChange={e => setSelectedFipTargetPort(e.target.value)} style={{ marginBottom: 4 }}>
                    <option value="">Track only / unattached</option>
                    {liveServerTargets.filter(t => t.portId).map(target => (
                      <option key={target.portId} value={target.portId}>{target.name} NIC port {shortId(target.portId)}</option>
                    ))}
                  </select>
                  <button className="chi-editor-deploy-btn" disabled={!selectedFipId || resourceBusy.startsWith('fip:')} onClick={handleAttachFloatingIpResource}>
                    Attach to slice
                  </button>

                  {floatingIpResources.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 4px' }}>Tracked Floating IPs ({filteredFloatingIpResources.length}/{floatingIpResources.length})</h5>
                      <CompactResourceTable
                        items={filteredFloatingIpResources}
                        getKey={(resource) => resource.resource_id || resourceProviderId(resource)}
                        emptyLabel="No tracked floating IPs match the current search."
                        testId="chameleon-floating-ip-table"
                        getRowTestId={() => 'chameleon-floating-ip-row'}
                        getRowAttributes={(resource) => ({
                          'data-resource-id': resource.resource_id,
                          'data-provider-id': resourceProviderId(resource),
                          'data-resource-name': resourceDisplayName(resource),
                          'data-site': resourceSite(resource),
                        })}
                        columns={[
                          {
                            key: 'ip',
                            label: 'IP',
                            render: (resource) => <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{resource.floating_ip || resource.name || shortId(resourceProviderId(resource))}</span>,
                          },
                          { key: 'site', label: 'Site', width: '82px', render: (resource) => resourceSite(resource) },
                          { key: 'port', label: 'Port', render: (resource) => resource.port_id ? shortId(resource.port_id) : 'unattached' },
                          { key: 'owner', label: 'Owner', width: '62px', render: (resource) => resource.ownership || 'managed' },
                          {
                            key: 'actions',
                            label: 'Actions',
                            render: (resource) => {
                              const id = resourceProviderId(resource);
                              const busy = resourceBusy === (resource.resource_id || id);
                              return (
                                <InlineActions>
                                  {resource.port_id && (
                                    <button className="chi-action-btn" style={{ fontSize: 10 }} disabled={busy} onClick={() => confirmEditorAction({
                                      title: 'Disassociate Floating IP',
                                      message: `Disassociate ${resource.floating_ip || resource.name} from its current port? The IP allocation remains.`,
                                      confirmLabel: 'Disassociate IP',
                                      onConfirm: async () => {
                                        await api.associateChameleonFloatingIp(id, resourceSite(resource), '');
                                        if (draft) {
                                          const updated = await api.addChameleonSliceResource(draft.id, { ...resource, port_id: '' });
                                          applyUpdatedDraft(updated, { refresh: false });
                                        }
                                        await refreshResourceInventory();
                                      },
                                    })}>Disassociate IP</button>
                                  )}
                                  <button className="chi-action-btn" style={{ fontSize: 10 }} disabled={busy} onClick={() => confirmEditorAction({
                                    title: 'Detach Floating IP From Slice',
                                    message: `Detach floating IP "${resource.floating_ip || resource.name || id}" from slice tracking? The IP allocation remains in Chameleon.`,
                                    confirmLabel: 'Detach from slice',
                                    onConfirm: () => detachSliceResource(resource),
                                  })}>Detach from slice</button>
                                  <button className="chi-action-btn chi-action-btn-danger" style={{ fontSize: 10 }} disabled={busy} onClick={() => confirmEditorAction({
                                    title: 'Release Floating IP',
                                    message: `Release floating IP "${resource.floating_ip || resource.name || id}" from Chameleon and detach it from this slice?`,
                                    danger: true,
                                    confirmLabel: 'Release floating IP',
                                    onConfirm: () => deleteSliceResource(resource),
                                  })}>Release floating IP</button>
                                </InlineActions>
                              );
                            },
                          },
                        ]}
                      />
                    </div>
                  )}
                </div>
              )}
              {chiEditorTab === 'resources' && (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                    <h5 style={{ fontSize: 11, fontWeight: 600, margin: 0 }}>Slice Resource Inventory</h5>
                    <button className="chi-action-btn" style={{ fontSize: 10 }} onClick={() => refreshResourceInventory()} disabled={loadingInventory}>
                      {loadingInventory ? 'Refreshing...' : 'Refresh'}
                    </button>
                  </div>
                  <FilterBox
                    value={resourceFilter}
                    onChange={setResourceFilter}
                    placeholder="Search resources by type, name, site, status, owner, ID..."
                    resultCount={filteredSliceResources.length + filteredAttachableSecurityGroups.length}
                    totalCount={sliceResources.length + securityGroups.filter(sg => !trackedSecurityGroupIds.has(sg.id)).length}
                    testId="chameleon-resource-filter"
                  />
                  {sliceResources.length === 0 ? (
                    <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)' }}>No tracked Chameleon resources in this slice.</div>
                  ) : (
                    <CompactResourceTable
                      items={filteredSliceResources}
                      getKey={(resource) => resource.resource_id || resourceProviderId(resource)}
                      emptyLabel="No tracked resources match the current search."
                      testId="chameleon-resource-table"
                      getRowTestId={() => 'chameleon-resource-row'}
                      getRowAttributes={(resource) => ({
                        'data-resource-id': resource.resource_id,
                        'data-provider-id': resourceProviderId(resource),
                        'data-resource-name': resourceDisplayName(resource),
                        'data-resource-type': resource.type,
                        'data-site': resourceSite(resource, ''),
                      })}
                      columns={[
                        { key: 'type', label: 'Type', width: '78px', render: (resource) => <span style={{ fontWeight: 700, textTransform: 'uppercase', color: 'var(--fabric-text-muted)' }}>{resource.type}</span> },
                        { key: 'name', label: 'Name', render: (resource) => resourceDisplayName(resource) },
                        {
                          key: 'status',
                          label: 'Status',
                          width: '70px',
                          render: (resource) => <span className={`chi-status ${statusClass(resource.status || 'UNKNOWN')}`} style={{ fontSize: 9 }}>{resource.status || 'UNKNOWN'}</span>,
                        },
                        { key: 'site', label: 'Site', width: '82px', render: (resource) => resourceSite(resource, '-') },
                        { key: 'owner', label: 'Owner', width: '70px', render: (resource) => resource.ownership || (resource.managed ? 'managed' : 'imported') },
                        { key: 'cleanup', label: 'Cleanup', width: '88px', render: (resource) => resource.delete_with_slice ? 'Delete' : 'Detach' },
                        { key: 'id', label: 'Provider ID', render: (resource) => <span style={{ fontFamily: 'monospace' }}>{shortId(resourceProviderId(resource))}</span> },
                        {
                          key: 'actions',
                          label: 'Actions',
                          render: (resource) => {
                            const id = resourceProviderId(resource);
                            const busy = resourceBusy === (resource.resource_id || id);
                            const details = resource.type === 'lease' ? leaseDetachDetails(resource) : [];
                            return (
                              <InlineActions>
                                <button className="chi-action-btn" style={{ fontSize: 10 }} disabled={busy} onClick={() => toggleDeleteWithSlice(resource)}>
                                  {resource.delete_with_slice ? 'Set detach only' : 'Delete with slice'}
                                </button>
                                <button className="chi-action-btn" style={{ fontSize: 10 }} disabled={busy} onClick={() => confirmEditorAction({
                                  title: `Detach ${resource.type} From Slice`,
                                  message: `Detach "${resourceDisplayName(resource)}" from this slice? The Chameleon resource will remain.`,
                                  details,
                                  confirmLabel: 'Detach from slice',
                                  onConfirm: () => detachSliceResource(resource),
                                })}>Detach from slice</button>
                                {['lease', 'instance', 'network', 'floating_ip', 'security_group'].includes(resource.type) && (
                                  <button className="chi-action-btn chi-action-btn-danger" style={{ fontSize: 10 }} disabled={busy} onClick={() => confirmEditorAction({
                                    title: `Delete ${resource.type} From Chameleon`,
                                    message: `Delete "${resourceDisplayName(resource)}" from Chameleon and detach it from this slice? This cannot be undone.`,
                                    details,
                                    danger: true,
                                    confirmLabel: 'Delete from Chameleon',
                                    onConfirm: () => deleteSliceResource(resource),
                                  })}>Delete from Chameleon</button>
                                )}
                              </InlineActions>
                            );
                          },
                        },
                      ]}
                    />
                  )}
                  {securityGroups.filter(sg => !trackedSecurityGroupIds.has(sg.id)).length > 0 && (
                    <div style={{ marginTop: 12, borderTop: '1px solid var(--fabric-border)', paddingTop: 8 }}>
                      <h5 style={{ fontSize: 11, fontWeight: 600, margin: '0 0 4px' }}>Attach Project Security Group</h5>
                      <CompactResourceTable
                        items={filteredAttachableSecurityGroups}
                        getKey={(sg) => sg.id}
                        emptyLabel="No project security groups match the current search."
                        testId="chameleon-security-group-table"
                        getRowTestId={() => 'chameleon-security-group-row'}
                        getRowAttributes={(sg) => ({
                          'data-provider-id': sg.id,
                          'data-resource-name': sg.name,
                          'data-site': resourceSite(sg, ''),
                        })}
                        columns={[
                          { key: 'name', label: 'Name', render: (sg) => sg.name || shortId(sg.id) },
                          { key: 'site', label: 'Site', width: '82px', render: (sg) => resourceSite(sg, '-') },
                          { key: 'rules', label: 'Rules', width: '58px', render: (sg) => (sg.security_group_rules || []).length },
                          { key: 'id', label: 'ID', render: (sg) => <span style={{ fontFamily: 'monospace' }}>{shortId(sg.id)}</span> },
                          {
                            key: 'action',
                            label: 'Action',
                            width: '92px',
                            render: (sg) => (
                              <button className="chi-editor-deploy-btn" style={{ fontSize: 11, padding: '2px 8px' }} disabled={resourceBusy === `sg:${sg.id}`} onClick={() => handleAttachSecurityGroupResource(sg)}>
                                {resourceBusy === `sg:${sg.id}` ? 'Attaching...' : 'Attach'}
                              </button>
                            ),
                          },
                        ]}
                      />
                    </div>
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
              data-testid="chameleon-draft-name"
            />
            <p style={{ fontSize: 11, color: 'var(--fabric-text-muted)', margin: '8px 0 0' }}>
              Sites are selected per-node when adding servers.
            </p>
            <button
              className="chi-editor-deploy-btn"
              style={{ marginTop: 12, width: '100%' }}
              onClick={handleCreateDraft}
              disabled={!newDraftName.trim()}
              data-testid="chameleon-create-draft"
            >
              Create Draft
            </button>
          </div>
        )}

        {/* --- Draft Header --- */}
        {state !== 'empty' && draft && (
          <div className="chi-editor-section chi-editor-header" data-testid="chameleon-draft-header" data-draft-id={draft.id} data-draft-name={draft.name}>
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
                data-testid="chameleon-discard-draft"
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
              data-testid="chameleon-node-name"
            />
            <label className="chi-form-label">Site</label>
            <select className="chi-form-input" value={nodeSite} onChange={e => { setNodeSite(e.target.value); setNodeType(''); setNodeImage(''); setNodeKeyName(''); }} data-testid="chameleon-node-site">
              {configuredSites.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
            </select>
            <label className="chi-form-label">Node Type {loadingData && '(loading...)'}</label>
            <ChameleonNodeTypeComboBox nodeTypes={nodeTypes} value={nodeType} onSelect={setNodeType} disabled={loadingData} />
            <label className="chi-form-label">Image</label>
            <ChameleonImageComboBox images={images} value={nodeImage} onSelect={setNodeImage} disabled={loadingData} />
            <label className="chi-form-label">SSH Key</label>
            <select
              className="chi-form-input"
              value={nodeKeyName}
              onChange={e => setNodeKeyName(e.target.value)}
              data-testid="chameleon-node-key"
              disabled={!!loadingKeypairsBySite[effectiveSite]}
            >
              <option value="">Use site default SSH key</option>
              {getKeypairNamesForSite(effectiveSite, nodeKeyName).map(keyName => (
                <option key={keyName} value={keyName}>{keyName}</option>
              ))}
            </select>
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
              data-testid="chameleon-node-count"
            />
            </div>
            <button
              className="chi-editor-deploy-btn"
              style={{ marginTop: 8, width: '100%' }}
              onClick={handleAddNode}
              disabled={addingNode || !nodeName.trim() || !nodeType}
              data-testid="chameleon-node-submit"
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
                <div key={n.id} className="chi-editor-item" data-testid="chameleon-draft-node-row" data-node-id={n.id} data-node-name={n.name}>
                  <div className="chi-editor-item-info">
                    <span className="chi-editor-item-name">{n.name}</span>
                    <span className="chi-editor-item-meta">
                      {n.node_type} / {n.image}{n.count > 1 ? ` x${n.count}` : ''}
                      {' '}| key: {n.key_name || 'site default'}
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
              data-testid="chameleon-network-name"
            />
            <label className="chi-form-label">Connected Nodes</label>
            <div className="chi-editor-checkbox-list">
              {(draft.nodes || []).map(n => (
                <label key={n.id} className="chi-editor-checkbox" data-testid="chameleon-network-node-option" data-node-id={n.id} data-node-name={n.name}>
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
              data-testid="chameleon-network-submit"
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
                <div key={net.id} className="chi-editor-item" data-testid="chameleon-draft-network-row" data-network-id={net.id} data-network-name={net.name}>
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
                setGraphDataIfChanged(null);
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
        <div className="toolbar-modal-overlay" onClick={() => setConfirmAction(null)}>
          <div className="toolbar-modal" onClick={e => e.stopPropagation()}>
            <h4>{confirmAction.title}</h4>
            <p>{confirmAction.message}</p>
            {confirmAction.details && confirmAction.details.length > 0 && (
              <ul style={{ margin: '8px 0', paddingLeft: 18, fontSize: 12, color: 'var(--fabric-text-muted)' }}>
                {confirmAction.details.map((detail, idx) => <li key={idx}>{detail}</li>)}
              </ul>
            )}
            <div className="toolbar-modal-actions">
              <button onClick={() => setConfirmAction(null)}>Cancel</button>
              <button className={confirmAction.danger ? 'danger' : 'primary'} onClick={() => { void confirmAction.onConfirm(); setConfirmAction(null); }}>
                {confirmAction.confirmLabel || (confirmAction.danger ? 'Delete' : 'Confirm')}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
