'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import type { SliceData, SiteInfo, ComponentModel, SliceNode, SliceNetwork, SliceFacilityPort, BootConfig, BootUpload, BootCommand, BootExecResult, FileEntry, SliceKeySet, VMTemplateSummary, HostInfo, IpHint, L3Config } from '../types/fabric';
import * as api from '../api/client';
import Tooltip from './Tooltip';
import SliverComboBox from './editor/SliverComboBox';
import ImageComboBox from './editor/ImageComboBox';
import AddSliverMenu, { type AddSliverType } from './editor/AddSliverMenu';
import '../styles/editor.css';

/** Return the first available name like "prefix1", "prefix2", etc. */
function nextName(prefix: string, existingNames: string[]): string {
  const used = new Set(existingNames);
  for (let i = 1; ; i++) {
    const candidate = `${prefix}${i}`;
    if (!used.has(candidate)) return candidate;
  }
}

interface DragHandleProps {
  draggable: boolean;
  onDragStart: (e: React.DragEvent) => void;
  onDragEnd: (e: React.DragEvent) => void;
}

interface EditorPanelProps {
  sliceData: SliceData | null;
  sliceName: string;
  onSliceUpdated: (data: SliceData) => void;
  onCollapse: () => void;
  sites: SiteInfo[];
  images: string[];
  componentModels: ComponentModel[];
  selectedElement?: Record<string, string> | null;
  dragHandleProps?: DragHandleProps;
  panelIcon?: string;
  vmTemplates?: VMTemplateSummary[];
  onSaveVmTemplate?: (nodeName: string) => void;
  onBootConfigErrors?: (errors: Array<{ node: string; type: string; id: string; detail: string }>) => void;
  onRunBootConfig?: () => void;
  bootRunning?: boolean;
}

export default function EditorPanel({ sliceData, sliceName, onSliceUpdated, onCollapse, sites, images, componentModels, selectedElement, dragHandleProps, panelIcon, vmTemplates = [], onSaveVmTemplate, onBootConfigErrors, onRunBootConfig, bootRunning }: EditorPanelProps) {
  const [selectedSliverKey, setSelectedSliverKey] = useState('');
  const [addMode, setAddMode] = useState<AddSliverType | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [editorTab, setEditorTab] = useState<'slice' | 'slivers'>('slice');

  // Per-slice key assignment
  const [keySets, setKeySets] = useState<SliceKeySet[]>([]);
  const [sliceKeyId, setSliceKeyId] = useState('');

  useEffect(() => {
    api.listSliceKeySets().then(setKeySets).catch(() => {});
  }, []);

  useEffect(() => {
    if (!sliceName) { setSliceKeyId(''); return; }
    api.getSliceKeyAssignment(sliceName).then((r) => setSliceKeyId(r.slice_key_id || '')).catch(() => setSliceKeyId(''));
  }, [sliceName]);

  const handleSliceKeyChange = async (keyId: string) => {
    setSliceKeyId(keyId);
    if (sliceName) {
      try { await api.setSliceKeyAssignment(sliceName, keyId); } catch { /* ignore */ }
    }
  };

  // When selectedElement changes from graph click, auto-select in combo box
  useEffect(() => {
    if (!selectedElement) return;
    const type = selectedElement.element_type;
    const name = selectedElement.name;
    if (!name) return;
    if (type === 'node') {
      setSelectedSliverKey(`node:${name}`);
      setAddMode(null);
      setEditorTab('slivers');
    } else if (type === 'network') {
      setSelectedSliverKey(`net:${name}`);
      setAddMode(null);
      setEditorTab('slivers');
    } else if (type === 'facility-port') {
      setSelectedSliverKey(`fp:${name}`);
      setAddMode(null);
      setEditorTab('slivers');
    }
  }, [selectedElement]);

  // If the selected sliver no longer exists, clear selection
  useEffect(() => {
    if (!selectedSliverKey || !sliceData) return;
    const [prefix, ...rest] = selectedSliverKey.split(':');
    const name = rest.join(':');
    if (prefix === 'node' && !sliceData.nodes.find((n) => n.name === name)) {
      setSelectedSliverKey('');
    } else if (prefix === 'net' && !sliceData.networks.find((n) => n.name === name)) {
      setSelectedSliverKey('');
    } else if (prefix === 'fp' && !(sliceData.facility_ports ?? []).find((f) => f.name === name)) {
      setSelectedSliverKey('');
    }
  }, [sliceData, selectedSliverKey]);

  const handleAddSelect = (type: AddSliverType) => {
    setAddMode(type);
    setSelectedSliverKey('');
  };

  const handleSliverSelect = (key: string) => {
    setSelectedSliverKey(key);
    setAddMode(null);
  };

  // Parse selected sliver
  const [sliverPrefix, ...sliverNameParts] = selectedSliverKey.split(':');
  const sliverName = sliverNameParts.join(':');
  const selectedNode: SliceNode | undefined = sliverPrefix === 'node' ? sliceData?.nodes.find((n) => n.name === sliverName) : undefined;
  const selectedNetwork: SliceNetwork | undefined = sliverPrefix === 'net' ? sliceData?.networks.find((n) => n.name === sliverName) : undefined;
  const selectedFP: SliceFacilityPort | undefined = sliverPrefix === 'fp' ? (sliceData?.facility_ports ?? []).find((f) => f.name === sliverName) : undefined;

  // Determine if slice has site groups (from template)
  const hasSiteGroups = sliceData?.nodes.some(n => n.site_group) ?? false;
  const isDraft = sliceData?.state === 'Draft';
  const isTerminal = sliceData?.state !== undefined && ['Dead', 'Closing', 'StableError'].includes(sliceData.state);
  const isActive = sliceData?.state !== undefined && ['StableOK', 'Active', 'ModifyOK'].includes(sliceData.state);
  const handleRunBootConfig = () => {
    if (!sliceName) return;
    if (onRunBootConfig) {
      onRunBootConfig();
    }
  };

  const [remapping, setRemapping] = useState(false);

  const handleRemapSites = async () => {
    setRemapping(true);
    setError('');
    try {
      const result = await api.resolveSites(sliceName, {}, true);
      onSliceUpdated(result);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRemapping(false);
    }
  };

  const apiCall = async (fn: () => Promise<SliceData>) => {
    setLoading(true);
    setError('');
    try {
      const result = await fn();
      onSliceUpdated(result);
      return result;
    } catch (e: any) {
      setError(e.message);
      return null;
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="editor-panel">
      <div className="editor-header" {...(dragHandleProps || {})}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span className="panel-drag-handle">{'\u283F'}</span>
          Editor
        </span>
        <button className="collapse-btn" onClick={(e) => { e.stopPropagation(); onCollapse(); }} title="Close panel">
          {'\u2715'}
        </button>
      </div>

      {/* Top-level Slice / Slivers tab bar */}
      <div className="editor-top-tabs">
        <button className={editorTab === 'slice' ? 'active' : ''} onClick={() => setEditorTab('slice')}>Slice</button>
        <button className={editorTab === 'slivers' ? 'active' : ''} onClick={() => setEditorTab('slivers')}>Slivers</button>
      </div>

      {/* ── Slice tab ── */}
      {editorTab === 'slice' && (
        <div className="tab-content">
          {error && <div style={{ color: 'var(--fabric-coral)', fontSize: 12, marginBottom: 8 }}>{error}</div>}

          {/* Slice info — name, UUID, state, dates */}
          {sliceData && (
            <div className="editor-slice-info" style={{ border: 'none', background: 'transparent', padding: '0 0 8px' }}>
              <span className="slice-info-name" title={sliceData.name}>{sliceData.name}</span>
              <span className={`slice-info-state state-${sliceData.state?.toLowerCase() || 'unknown'}`}>{sliceData.state || '\u2014'}</span>
              {sliceData.id && <span className="slice-info-field" title={sliceData.id}>UUID: {sliceData.id.slice(0, 8)}...</span>}
              {sliceData.lease_start && <span className="slice-info-field">Start: {new Date(sliceData.lease_start).toLocaleString()}</span>}
              {sliceData.lease_end && <span className="slice-info-field">Expires: {new Date(sliceData.lease_end).toLocaleString()}</span>}
            </div>
          )}

          {/* Lease renew (active slices) */}
          {isActive && sliceData && (
            <LeaseRenewSection sliceName={sliceName} leaseEnd={sliceData.lease_end} onSliceUpdated={onSliceUpdated} />
          )}

          {/* Run Boot Config (active slices) */}
          {isActive && (
            <div style={{ marginBottom: 12 }}>
              <Tooltip text="Run boot configuration (uploads, network config, commands) on all nodes">
                <button
                  className="site-mapping-auto-btn"
                  style={{ width: '100%', fontSize: 11, padding: '5px 0' }}
                  onClick={handleRunBootConfig}
                  disabled={bootRunning}
                >
                  {bootRunning ? '\u21BB Running...' : '\u25B6 Run Boot Config'}
                </button>
              </Tooltip>
            </div>
          )}

          {/* Auto-assign section — available for any draft with nodes */}
          {isDraft && sliceData && sliceData.nodes.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div className="auto-assign-description">
                Automatically place each node on a FABRIC site and host with enough resources for your VMs.
              </div>
              <button
                className="site-mapping-auto-btn"
                style={{ width: '100%', fontSize: 11, padding: '5px 0' }}
                onClick={handleRemapSites}
                disabled={remapping || loading}
                data-help-id="editor.remap-sites"
              >
                {remapping ? 'Resolving...' : '\u21BB Auto-Assign Sites & Hosts'}
              </button>
            </div>
          )}

          {/* Per-slice SSH key selector */}
          {sliceName && keySets.length > 0 && (
            <div className="slice-key-select" style={{ border: 'none', padding: '0 0 8px' }}>
              <label>SSH Key:</label>
              <select value={sliceKeyId} onChange={(e) => handleSliceKeyChange(e.target.value)}>
                <option value="">(default{keySets.find(k => k.is_default) ? `: ${keySets.find(k => k.is_default)!.name}` : ''})</option>
                {keySets.filter(k => !k.is_default).map((ks) => (
                  <option key={ks.name} value={ks.name}>{ks.name}</option>
                ))}
              </select>
            </div>
          )}

          {/* Site Mapping (draft slices with @group tags) */}
          {hasSiteGroups && isDraft && sliceData && (
            <SiteMappingView
              sliceData={sliceData}
              sliceName={sliceName}
              sites={sites}
              loading={loading}
              onSliceUpdated={onSliceUpdated}
              setLoading={setLoading}
              setError={setError}
            />
          )}

          {/* Empty state when no slice loaded */}
          {!sliceData && (
            <div className="editor-empty">
              No slice loaded.
            </div>
          )}
        </div>
      )}

      {/* ── Slivers tab ── */}
      {editorTab === 'slivers' && (
        <>
          {/* Sliver selector + Add button */}
          <div className="editor-sliver-bar" data-help-id="editor.sliver-selector">
            <SliverComboBox
              sliceData={sliceData}
              selectedSliverKey={selectedSliverKey}
              onSelect={handleSliverSelect}
              errorMessages={sliceData?.error_messages}
            />
            {!isTerminal && <AddSliverMenu onSelect={handleAddSelect} />}
          </div>

          <div className="tab-content">
            {error && <div style={{ color: 'var(--fabric-coral)', fontSize: 12, marginBottom: 8 }}>{error}</div>}

            {/* Add mode forms */}
            {addMode === 'node' && (
              <NodeForm
                mode="add"
                sites={sites}
                images={images}
                componentModels={componentModels}
                sliceName={sliceName}
                loading={loading}
                sliceData={sliceData}
                vmTemplates={vmTemplates}
                onSubmit={async (data) => {
                  let result = await apiCall(() => api.addNode(sliceName, data));
                  if (result) {
                    if (data._pendingComponents?.length) {
                      for (const comp of data._pendingComponents) {
                        try {
                          result = await apiCall(() => api.addComponent(sliceName, data.name, comp)) || result;
                        } catch { /* ignore */ }
                      }
                    }
                    if (data._pendingBootConfig) {
                      try {
                        await api.saveBootConfig(sliceName, data.name, data._pendingBootConfig);
                      } catch { /* ignore */ }
                    }
                    setSelectedSliverKey(`node:${data.name}`);
                    setAddMode(null);
                  }
                }}
              />
            )}
            {addMode === 'l2network' && (
              <NetworkForm
                mode="add"
                defaultLayer="L2"
                sliceData={sliceData}
                sliceName={sliceName}
                loading={loading}
                onSubmit={async (data) => {
                  const result = await apiCall(() => api.addNetwork(sliceName, data));
                  if (result) {
                    setSelectedSliverKey(`net:${data.name}`);
                    setAddMode(null);
                  }
                }}
              />
            )}
            {addMode === 'l3network' && (
              <NetworkForm
                mode="add"
                defaultLayer="L3"
                sliceData={sliceData}
                sliceName={sliceName}
                loading={loading}
                onSubmit={async (data) => {
                  const result = await apiCall(() => api.addNetwork(sliceName, data));
                  if (result) {
                    setSelectedSliverKey(`net:${data.name}`);
                    setAddMode(null);
                  }
                }}
              />
            )}
            {addMode === 'facility-port' && (
              <FacilityPortForm
                mode="add"
                sites={sites}
                sliceName={sliceName}
                loading={loading}
                sliceData={sliceData}
                onSubmit={async (data) => {
                  const result = await apiCall(() => api.addFacilityPort(sliceName, data));
                  if (result) {
                    setSelectedSliverKey(`fp:${data.name}`);
                    setAddMode(null);
                  }
                }}
              />
            )}

            {/* Edit mode: selected node */}
            {!addMode && selectedNode && (
              <NodeForm
                key={`edit-node-${selectedNode.name}`}
                mode="edit"
                node={selectedNode}
                sites={sites}
                images={images}
                componentModels={componentModels}
                sliceName={sliceName}
                loading={loading}
                sliceData={sliceData}
                vmTemplates={vmTemplates}
                onSubmit={async (data) => {
                  await apiCall(() => api.updateNode(sliceName, selectedNode.name, data));
                }}
                onDelete={async () => {
                  await apiCall(() => api.removeNode(sliceName, selectedNode.name));
                  setSelectedSliverKey('');
                }}
                onAddComponent={async (compData) => {
                  await apiCall(() => api.addComponent(sliceName, selectedNode.name, compData));
                }}
                onDeleteComponent={async (compName) => {
                  await apiCall(() => api.removeComponent(sliceName, selectedNode.name, compName));
                }}
                onSaveVmTemplate={onSaveVmTemplate ? (nodeName) => onSaveVmTemplate(nodeName) : undefined}
              />
            )}

            {/* Edit mode: selected network */}
            {!addMode && selectedNetwork && (
              <NetworkReadOnlyView
                network={selectedNetwork}
                loading={loading}
                isDraft={isDraft}
                sliceName={sliceName}
                onSliceUpdated={onSliceUpdated}
                onDelete={async () => {
                  await apiCall(() => api.removeNetwork(sliceName, selectedNetwork.name));
                  setSelectedSliverKey('');
                }}
              />
            )}

            {/* Edit mode: selected facility port (read-only) */}
            {!addMode && selectedFP && (
              <FacilityPortReadOnlyView
                fp={selectedFP}
                loading={loading}
                onDelete={async () => {
                  await apiCall(() => api.removeFacilityPort(sliceName, selectedFP.name));
                  setSelectedSliverKey('');
                }}
              />
            )}

            {/* Nothing selected, no add mode */}
            {!addMode && !selectedNode && !selectedNetwork && !selectedFP && (
              <div className="editor-empty">
                Select a sliver to edit, or click <strong>+</strong> to add one.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}


// --- Lease Renew Section ---
function LeaseRenewSection({ sliceName, leaseEnd, onSliceUpdated }: { sliceName: string; leaseEnd: string; onSliceUpdated: (data: SliceData) => void }) {
  const defaultDate = (() => {
    try {
      const d = new Date(leaseEnd);
      d.setDate(d.getDate() + 1);
      return d.toISOString().slice(0, 16);
    } catch {
      return '';
    }
  })();
  const [renewDate, setRenewDate] = useState(defaultDate);
  const [renewLoading, setRenewLoading] = useState(false);
  const [renewError, setRenewError] = useState('');
  const [renewSuccess, setRenewSuccess] = useState('');

  const handleRenew = async () => {
    if (!renewDate) return;
    setRenewLoading(true);
    setRenewError('');
    setRenewSuccess('');
    try {
      const result = await api.renewLease(sliceName, renewDate);
      onSliceUpdated(result);
      setRenewSuccess('Lease renewed successfully');
    } catch (e: any) {
      setRenewError(e.message);
    } finally {
      setRenewLoading(false);
    }
  };

  return (
    <div className="lease-renew-section">
      <div className="editor-section-label">Renew Lease</div>
      <div className="form-group" style={{ marginBottom: 8 }}>
        <label style={{ fontSize: 11, color: 'var(--fabric-text-muted)' }}>New end date:</label>
        <input
          type="datetime-local"
          value={renewDate}
          onChange={(e) => setRenewDate(e.target.value)}
          style={{ width: '100%', fontSize: 12, padding: '4px 6px' }}
        />
      </div>
      <button
        className="site-mapping-auto-btn"
        style={{ width: '100%', fontSize: 11, padding: '5px 0' }}
        onClick={handleRenew}
        disabled={renewLoading || !renewDate}
      >
        {renewLoading ? 'Renewing...' : 'Renew Lease'}
      </button>
      {renewError && <div style={{ color: 'var(--fabric-coral)', fontSize: 11, marginTop: 4 }}>{renewError}</div>}
      {renewSuccess && <div style={{ color: 'var(--fabric-teal)', fontSize: 11, marginTop: 4 }}>{renewSuccess}</div>}
    </div>
  );
}


// --- Site Mapping View ---
function SiteMappingView({
  sliceData, sliceName, sites, loading, onSliceUpdated, setLoading, setError,
}: {
  sliceData: SliceData;
  sliceName: string;
  sites: SiteInfo[];
  loading: boolean;
  onSliceUpdated: (data: SliceData) => void;
  setLoading: (v: boolean) => void;
  setError: (v: string) => void;
}) {
  const [resolving, setResolving] = useState(false);
  const [localOverrides, setLocalOverrides] = useState<Record<string, string>>({});

  // Build group data from nodes
  const groupMap: Record<string, { nodes: SliceNode[]; totalCores: number; totalRam: number; totalDisk: number; currentSite: string }> = {};
  for (const node of sliceData.nodes) {
    const grp = node.site_group;
    if (!grp) continue;
    if (!groupMap[grp]) {
      groupMap[grp] = { nodes: [], totalCores: 0, totalRam: 0, totalDisk: 0, currentSite: node.site };
    }
    groupMap[grp].nodes.push(node);
    groupMap[grp].totalCores += node.cores;
    groupMap[grp].totalRam += node.ram;
    groupMap[grp].totalDisk += node.disk;
    groupMap[grp].currentSite = node.site; // all nodes in group share same site
  }

  const groups = Object.entries(groupMap).sort((a, b) => a[0].localeCompare(b[0]));
  const activeSites = sites.filter(s => s.state === 'Active');

  const handleGroupSiteChange = async (group: string, newSite: string) => {
    const newOverrides = { ...localOverrides, [group]: newSite };
    setLocalOverrides(newOverrides);
    // Apply immediately
    setResolving(true);
    setError('');
    try {
      const result = await api.resolveSites(sliceName, newOverrides);
      onSliceUpdated(result);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setResolving(false);
    }
  };

  const handleAutoAssign = async () => {
    setResolving(true);
    setError('');
    try {
      // Pass only the manually overridden groups; everything else re-resolves
      const result = await api.resolveSites(sliceName, localOverrides);
      onSliceUpdated(result);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setResolving(false);
    }
  };

  const handleResetOverrides = async () => {
    setLocalOverrides({});
    setResolving(true);
    setError('');
    try {
      const result = await api.resolveSites(sliceName, {});
      onSliceUpdated(result);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setResolving(false);
    }
  };

  if (groups.length === 0) {
    return <div className="editor-empty">No site groups in this slice.</div>;
  }

  return (
    <div className="site-mapping-section">
      <div className="site-mapping-header">
        <span className="site-mapping-title">Site Mapping</span>
        <div style={{ display: 'flex', gap: 4 }}>
          {Object.keys(localOverrides).length > 0 && (
            <Tooltip text="Clear all manual site overrides and re-resolve every group using live resource availability">
              <button
                className="site-mapping-auto-btn"
                onClick={handleResetOverrides}
                disabled={resolving}
                style={{ background: 'transparent', color: 'var(--fabric-text-muted)', borderColor: 'var(--fabric-border)' }}
              >
                Reset
              </button>
            </Tooltip>
          )}
          <Tooltip text="Re-resolve site assignments using current resource availability. Pinned groups keep their assigned site.">
            <button
              className="site-mapping-auto-btn"
              onClick={handleAutoAssign}
              disabled={resolving}
              data-help-id="editor.auto-assign"
            >
              {resolving ? 'Resolving...' : 'Auto-Assign'}
            </button>
          </Tooltip>
        </div>
      </div>

      <div className="site-mapping-list">
        {groups.map(([group, info]) => {
          const currentSite = info.currentSite;
          const siteInfo = sites.find(s => s.name === currentSite);
          const insufficientResources = siteInfo && (
            siteInfo.cores_available < info.totalCores ||
            siteInfo.ram_available < info.totalRam ||
            siteInfo.disk_available < info.totalDisk
          );

          return (
            <div key={group} className={`site-mapping-row${insufficientResources ? ' warning' : ''}`}>
              <div className="site-mapping-group-header">
                <span className="site-mapping-group-tag">{group}</span>
                <span className="site-mapping-node-count">{info.nodes.length} node{info.nodes.length !== 1 ? 's' : ''}</span>
                {localOverrides[group] && (
                  <span style={{ fontSize: 9, color: 'var(--fabric-orange)', fontWeight: 600 }}>PINNED</span>
                )}
              </div>
              <div className="site-mapping-resources">
                {info.totalCores} cores, {info.totalRam} GB RAM, {info.totalDisk} GB disk
              </div>
              <div className="site-mapping-select-row">
                <select
                  value={currentSite || ''}
                  onChange={(e) => handleGroupSiteChange(group, e.target.value)}
                  disabled={resolving}
                >
                  {!currentSite && (
                    <option value="" disabled>-- Not assigned --</option>
                  )}
                  {activeSites.map(s => (
                    <option key={s.name} value={s.name}>
                      {s.name} ({s.cores_available}c / {s.ram_available}G)
                    </option>
                  ))}
                </select>
              </div>
              {insufficientResources && (
                <div className="site-mapping-warning">
                  {'\u26A0'} Site may lack sufficient resources for this group
                </div>
              )}
              <div className="site-mapping-nodes-list">
                {info.nodes.map(n => n.name).join(', ')}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}


// --- Feasibility helpers ---

/** Sum cores/ram/disk of other nodes at the same site (excluding `excludeNodeName`). */
function siblingUsageAtSite(sliceData: SliceData | null | undefined, siteName: string, excludeNodeName?: string): { cores: number; ram: number; disk: number } {
  if (!sliceData) return { cores: 0, ram: 0, disk: 0 };
  let cores = 0, ram = 0, disk = 0;
  for (const n of sliceData.nodes) {
    if (n.name === excludeNodeName) continue;
    if (n.site === siteName) {
      cores += n.cores; ram += n.ram; disk += n.disk;
    }
  }
  return { cores, ram, disk };
}

/** Sum cores/ram/disk of other nodes at the same host (excluding `excludeNodeName`). */
function siblingUsageAtHost(sliceData: SliceData | null | undefined, hostName: string, excludeNodeName?: string): { cores: number; ram: number; disk: number } {
  if (!sliceData) return { cores: 0, ram: 0, disk: 0 };
  let cores = 0, ram = 0, disk = 0;
  for (const n of sliceData.nodes) {
    if (n.name === excludeNodeName) continue;
    if (n.host === hostName) {
      cores += n.cores; ram += n.ram; disk += n.disk;
    }
  }
  return { cores, ram, disk };
}

/** Check if a site can fit the given resource needs after subtracting sibling usage. */
function siteCanFit(site: SiteInfo, cores: number, ram: number, disk: number, sibling: { cores: number; ram: number; disk: number }): boolean {
  return (site.cores_available - sibling.cores) >= cores &&
         (site.ram_available - sibling.ram) >= ram &&
         (site.disk_available - sibling.disk) >= disk;
}

/** Check if a host can fit the given resource needs after subtracting sibling usage. */
function hostCanFit(host: HostInfo, cores: number, ram: number, disk: number, sibling: { cores: number; ram: number; disk: number }): boolean {
  return (host.cores_available - sibling.cores) >= cores &&
         (host.ram_available - sibling.ram) >= ram &&
         (host.disk_available - sibling.disk) >= disk;
}

// --- Host ComboBox ---

function HostComboBox({ hosts, hostsLoading, value, onChange, disabled, cores, ram, disk, sliceData, excludeNodeName }: {
  hosts: HostInfo[];
  hostsLoading: boolean;
  value: string;
  onChange: (host: string) => void;
  disabled?: boolean;
  cores: number;
  ram: number;
  disk: number;
  sliceData?: SliceData | null;
  excludeNodeName?: string;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const filtered = hosts.filter(h => !filter || h.name.toLowerCase().includes(filter.toLowerCase()));
  const selectedHost = hosts.find(h => h.name === value);

  return (
    <div className="host-combo" ref={ref}>
      <div
        className={`host-combo-input${disabled ? ' disabled' : ''}`}
        onClick={() => { if (!disabled) { setOpen(!open); setFilter(''); } }}
      >
        {open && !disabled ? (
          <input
            className="host-combo-filter"
            autoFocus
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            placeholder="Filter hosts..."
          />
        ) : value ? (
          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {value}
            {selectedHost && (() => {
              const sib = siblingUsageAtHost(sliceData, value, excludeNodeName);
              const fits = hostCanFit(selectedHost, cores, ram, disk, sib);
              return <span className={fits ? 'feasibility-ok' : 'feasibility-warn'}> {fits ? '\u2713' : '\u26A0'}</span>;
            })()}
          </span>
        ) : (
          <span className="host-combo-placeholder">
            {disabled ? 'Select a site first' : hostsLoading ? 'Loading...' : 'Any host (auto)'}
          </span>
        )}
        <span className="host-combo-arrow">{'\u25BC'}</span>
      </div>
      {open && !disabled && (
        <div className="host-combo-dropdown">
          {/* Auto option */}
          <div
            className={`host-combo-option${!value ? ' selected' : ''}`}
            onClick={() => { onChange(''); setOpen(false); }}
          >
            <span className="host-combo-opt-name" style={{ fontStyle: 'italic' }}>Any host (auto)</span>
          </div>
          {hostsLoading ? (
            <div className="host-combo-empty">Loading hosts...</div>
          ) : filtered.length === 0 ? (
            <div className="host-combo-empty">No hosts found</div>
          ) : filtered.map(h => {
            const sib = siblingUsageAtHost(sliceData, h.name, excludeNodeName);
            const adjCores = h.cores_available - sib.cores;
            const adjRam = h.ram_available - sib.ram;
            const adjDisk = h.disk_available - sib.disk;
            const fits = adjCores >= cores && adjRam >= ram && adjDisk >= disk;
            return (
              <div
                key={h.name}
                className={`host-combo-option${h.name === value ? ' selected' : ''}`}
                onClick={() => { onChange(h.name); setOpen(false); }}
              >
                <span className={fits ? 'feasibility-ok' : 'feasibility-warn'}>{fits ? '\u2713' : '\u26A0'}</span>
                <span className="host-combo-opt-name">{h.name}</span>
                <span className="host-combo-opt-resources">{adjCores}c / {adjRam}G / {adjDisk}G</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}


// --- Node Form (add + edit) ---
function NodeForm({
  mode, node, sites, images, componentModels, sliceName, loading,
  sliceData, vmTemplates = [], onSubmit, onDelete, onAddComponent, onDeleteComponent, onSaveVmTemplate,
}: {
  mode: 'add' | 'edit';
  node?: SliceNode;
  sites: SiteInfo[];
  images: string[];
  componentModels: ComponentModel[];
  sliceName: string;
  loading: boolean;
  sliceData?: SliceData | null;
  vmTemplates?: VMTemplateSummary[];
  onSubmit: (data: any) => void;
  onDelete?: () => void;
  onAddComponent?: (data: { name: string; model: string }) => void;
  onDeleteComponent?: (name: string) => void;
  onSaveVmTemplate?: (nodeName: string) => void;
}) {
  // Pre-fill name for add mode
  const defaultName = mode === 'add' && sliceData
    ? nextName('vm', sliceData.nodes.map((n) => n.name))
    : (node?.name ?? '');
  const [name, setName] = useState(defaultName);
  const [site, setSite] = useState(node?.site ?? 'auto');
  const [host, setHost] = useState(node?.host ?? '');
  const [hosts, setHosts] = useState<HostInfo[]>([]);
  const [hostsLoading, setHostsLoading] = useState(false);
  const [cores, setCores] = useState(node?.cores ?? 2);
  const [ram, setRam] = useState(node?.ram ?? 8);
  const [disk, setDisk] = useState(node?.disk ?? 10);
  const [image, setImage] = useState(node?.image ?? 'default_ubuntu_22');

  // Fetch hosts when site changes
  useEffect(() => {
    if (!site || site === 'auto') {
      setHosts([]);
      setHost('');
      return;
    }
    let cancelled = false;
    setHostsLoading(true);
    api.listSiteHosts(site).then(h => {
      if (!cancelled) { setHosts(h); setHostsLoading(false); }
    }).catch(() => {
      if (!cancelled) { setHosts([]); setHostsLoading(false); }
    });
    return () => { cancelled = true; };
  }, [site]);
  const [pendingBootConfig, setPendingBootConfig] = useState<BootConfig | null>(null);
  const [appliedTemplateName, setAppliedTemplateName] = useState('');

  // Component add sub-form — pre-fill based on model prefix and node's existing components
  const compPrefix = useCallback((model: string) => {
    const m = model.toLowerCase();
    if (m.includes('gpu')) return 'gpu';
    if (m.includes('fpga')) return 'fpga';
    if (m.includes('nvme')) return 'nvme';
    return 'nic';
  }, []);
  const [compModel, setCompModel] = useState('NIC_Basic');
  const existingCompNames = node?.components.map((c) => c.name) ?? [];
  const [compName, setCompName] = useState(() => nextName(compPrefix('NIC_Basic'), existingCompNames));

  // Components to add with node in add mode
  const [pendingComponents, setPendingComponents] = useState<Array<{ name: string; model: string }>>([]);

  const handleImageSelect = useCallback(async (newImage: string, vmTemplate?: VMTemplateSummary) => {
    setImage(newImage);
    if (vmTemplate) {
      // Fetch full detail to get boot_config + node properties (cores, ram, disk, site, components)
      try {
        let bootConfig: import('../types/fabric').BootConfig | undefined;
        let detail: import('../types/fabric').VMTemplateDetail | undefined;
        if (vmTemplate.variant_count > 0) {
          const variant = await api.getVmTemplateVariant(vmTemplate.dir_name, newImage);
          bootConfig = variant.boot_config;
          // Also fetch full detail for node-level properties
          detail = await api.getVmTemplate(vmTemplate.dir_name);
        } else {
          detail = await api.getVmTemplate(vmTemplate.dir_name);
          bootConfig = detail.boot_config;
        }
        // Apply node-level properties from the template
        if (detail) {
          if (detail.cores) setCores(detail.cores);
          if (detail.ram) setRam(detail.ram);
          if (detail.disk) setDisk(detail.disk);
          if (detail.site) setSite(detail.site);
          if (mode === 'add' && detail.components?.length) {
            const usedNames = [...existingCompNames];
            setPendingComponents(detail.components.map(c => {
              const n = nextName(compPrefix(c.model), usedNames);
              usedNames.push(n);
              return { name: n, model: c.model };
            }));
          }
        }
        if (bootConfig) {
          if (mode === 'add') {
            setPendingBootConfig(bootConfig);
            setAppliedTemplateName(vmTemplate.name);
          } else if (mode === 'edit' && node) {
            await api.saveBootConfig(sliceName, node.name, bootConfig);
            setAppliedTemplateName(vmTemplate.name);
          }
        }
      } catch { /* ignore */ }
    } else {
      setPendingBootConfig(null);
      setAppliedTemplateName('');
    }
  }, [mode, node, sliceName, existingCompNames, compPrefix]);

  // Sync when node changes
  useEffect(() => {
    if (mode === 'edit' && node) {
      setName(node.name);
      setSite(node.site || 'auto');
      setHost(node.host || '');
      setCores(node.cores);
      setRam(node.ram);
      setDisk(node.disk);
      setImage(node.image || 'default_ubuntu_22');
    }
  }, [mode, node]);

  const isLocked = sliceData?.state !== undefined && sliceData.state !== 'Draft';
  const isNodeActive = node?.reservation_state === 'Active';

  const [nodeTab, setNodeTab] = useState<'edit' | 'components' | 'boot' | 'files' | 'shell'>('edit');

  // Reset tab when switching nodes or modes
  useEffect(() => {
    setNodeTab('edit');
  }, [node?.name, mode]);

  // --- Add mode: plain form, no tabs ---
  if (mode === 'add') {
    return (
      <>
        <div className="editor-section-label">Add VM Node</div>

        <div className="form-group" data-help-id="editor.node.name">
          <label><Tooltip text="Unique name for this VM within the slice">Name</Tooltip></label>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="node1" />
        </div>
        <div className="form-group" data-help-id="editor.node.site">
          <label><Tooltip text="FABRIC site where the VM will be deployed">Site</Tooltip></label>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <select value={site} onChange={(e) => { setSite(e.target.value); setHost(''); }} style={{ flex: 1 }}>
              <option value="auto">auto</option>
              {sites.filter(s => s.state === 'Active').map((s) => {
                const sib = siblingUsageAtSite(sliceData, s.name, node?.name);
                const fits = siteCanFit(s, cores, ram, disk, sib);
                const adjCores = s.cores_available - sib.cores;
                const adjRam = s.ram_available - sib.ram;
                return <option key={s.name} value={s.name}>{fits ? '\u2713' : '\u26A0'} {s.name} ({adjCores}c / {adjRam}G)</option>;
              })}
            </select>
            {node?.site_group && (
              <span style={{ color: '#008e7a', fontSize: '0.85em', whiteSpace: 'nowrap' }} title="Co-location group from template">group: {node.site_group}</span>
            )}
          </div>
        </div>
        <div className="form-group" data-help-id="editor.node.host">
          <label><Tooltip text="Pin VM to a specific physical host, or leave as auto">Host</Tooltip></label>
          <HostComboBox
            hosts={hosts}
            hostsLoading={hostsLoading}
            value={host}
            onChange={setHost}
            disabled={!site || site === 'auto'}
            cores={cores}
            ram={ram}
            disk={disk}
            sliceData={sliceData}
            excludeNodeName={node?.name}
          />
        </div>
        <div className="form-group" data-help-id="editor.node.cores">
          <label><Tooltip text="CPU cores (1-64)">Cores</Tooltip> <span className="range-value">{cores}</span></label>
          <input type="range" min={1} max={64} value={cores} onChange={(e) => setCores(+e.target.value)} />
        </div>
        <div className="form-group" data-help-id="editor.node.ram">
          <label><Tooltip text="RAM in GB (2-256)">RAM (GB)</Tooltip> <span className="range-value">{ram}</span></label>
          <input type="range" min={2} max={256} value={ram} onChange={(e) => setRam(+e.target.value)} />
        </div>
        <div className="form-group" data-help-id="editor.node.disk">
          <label><Tooltip text="Root disk in GB (10-500)">Disk (GB)</Tooltip> <span className="range-value">{disk}</span></label>
          <input type="range" min={10} max={500} value={disk} onChange={(e) => setDisk(+e.target.value)} />
        </div>
        <div className="form-group" data-help-id="editor.node.image">
          <label><Tooltip text="OS image or VM template">Image</Tooltip></label>
          <ImageComboBox
            images={images}
            vmTemplates={vmTemplates}
            value={image}
            onSelect={handleImageSelect}
          />
        </div>
        {appliedTemplateName && (
          <div style={{ fontSize: 10, color: 'var(--fabric-teal)', marginTop: -4, marginBottom: 4, paddingLeft: 2 }}>
            VM template applied: {appliedTemplateName}
          </div>
        )}

        {/* Components section for add mode */}
        <div className="editor-section-divider" style={{ margin: '12px 0 8px' }} />
        <div className="editor-section-label">Components</div>

        {pendingComponents.length > 0 && (
          <div className="component-list" style={{ marginBottom: 8 }}>
            {pendingComponents.map((comp, idx) => (
              <div key={idx} className="component-row">
                <span className="component-row-name">{comp.name}</span>
                <span className="component-row-model">{comp.model}</span>
                <button
                  className="component-row-delete"
                  onClick={() => {
                    setPendingComponents(pendingComponents.filter((_, i) => i !== idx));
                  }}
                  title={`Remove ${comp.name}`}
                >
                  {'\u2715'}
                </button>
              </div>
            ))}
          </div>
        )}

        {componentModels.length > 0 && (
          <div className="form-group" data-help-id="editor.comp.model">
            <label><Tooltip text="Hardware type to attach">Add Component</Tooltip></label>
            <select value={compModel} onChange={(e) => {
              setCompModel(e.target.value);
              const allNames = [...(node?.components.map((c) => c.name) ?? []), ...pendingComponents.map((c) => c.name)];
              setCompName(nextName(compPrefix(e.target.value), allNames));
            }} style={{ marginBottom: 4 }}>
              {componentModels.map((c) => (
                <option key={c.model} value={c.model}>{c.model} — {c.description}</option>
              ))}
            </select>
            <div style={{ display: 'flex', gap: 4 }}>
              <input
                type="text"
                value={compName}
                onChange={(e) => setCompName(e.target.value)}
                placeholder="nic1"
                style={{ flex: 1 }}
              />
              <button
                disabled={!compName}
                onClick={() => {
                  setPendingComponents([...pendingComponents, { name: compName, model: compModel }]);
                  const allNames = [...(node?.components.map((c) => c.name) ?? []), ...pendingComponents.map((c) => c.name), compName];
                  setCompName(nextName(compPrefix(compModel), allNames));
                }}
              >
                Add
              </button>
            </div>
          </div>
        )}

        <div className="form-actions">
          <button
            className="primary"
            disabled={loading || !name || !sliceName}
            onClick={() => onSubmit({ name, site, host: host || undefined, cores, ram, disk, image, _pendingBootConfig: pendingBootConfig, _pendingComponents: pendingComponents })}
          >
            Add Node
          </button>
        </div>
      </>
    );
  }

  // --- Edit mode: tabbed UI ---
  return (
    <>
      <div className="editor-section-label">Node: {node?.name}</div>

      <div className="node-edit-tabs">
        <button className={nodeTab === 'edit' ? 'active' : ''} onClick={() => setNodeTab('edit')}>Edit</button>
        <button className={nodeTab === 'components' ? 'active' : ''} onClick={() => setNodeTab('components')}>
          Components{node && node.components.length > 0 ? ` (${node.components.length})` : ''}
        </button>
        <button className={nodeTab === 'boot' ? 'active' : ''} onClick={() => setNodeTab('boot')} data-help-id="editor.boot-config">Boot Config</button>
        {isNodeActive && (
          <>
            <button className={nodeTab === 'files' ? 'active' : ''} onClick={() => setNodeTab('files')}>Files</button>
            <button className={nodeTab === 'shell' ? 'active' : ''} onClick={() => setNodeTab('shell')}>Shell</button>
          </>
        )}
      </div>

      {/* Edit tab */}
      {nodeTab === 'edit' && (
        <>
          {isLocked ? (
            <>
              <div className="readonly-field">
                <span className="readonly-label">Name</span>
                <span className="readonly-value">{node?.name}</span>
              </div>
              <div className="readonly-field">
                <span className="readonly-label">Site</span>
                <span className="readonly-value">{node?.site || 'auto'}</span>
              </div>
              {node?.host && (
                <div className="readonly-field">
                  <span className="readonly-label">Host</span>
                  <span className="readonly-value">{node.host}</span>
                </div>
              )}
              <div className="readonly-field">
                <span className="readonly-label">Cores</span>
                <span className="readonly-value">{node?.cores}</span>
              </div>
              <div className="readonly-field">
                <span className="readonly-label">RAM</span>
                <span className="readonly-value">{node?.ram} GB</span>
              </div>
              <div className="readonly-field">
                <span className="readonly-label">Disk</span>
                <span className="readonly-value">{node?.disk} GB</span>
              </div>
              <div className="readonly-field">
                <span className="readonly-label">Image</span>
                <span className="readonly-value">{node?.image}</span>
              </div>
              {node?.reservation_state && (
                <div className="readonly-field">
                  <span className="readonly-label">State</span>
                  <span className="readonly-value">{node.reservation_state}</span>
                </div>
              )}
              {node?.management_ip && (
                <div className="readonly-field">
                  <span className="readonly-label">Mgmt IP</span>
                  <span className="readonly-value">{node.management_ip}</span>
                </div>
              )}
            </>
          ) : (
            <>
              <div className="form-group" data-help-id="editor.node.site">
                <label><Tooltip text="FABRIC site where the VM will be deployed">Site</Tooltip></label>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <select value={site} onChange={(e) => { setSite(e.target.value); setHost(''); }} style={{ flex: 1 }}>
                    <option value="auto">auto</option>
                    {sites.filter(s => s.state === 'Active').map((s) => {
                      const sib = siblingUsageAtSite(sliceData, s.name, node?.name);
                      const fits = siteCanFit(s, cores, ram, disk, sib);
                      const adjCores = s.cores_available - sib.cores;
                      const adjRam = s.ram_available - sib.ram;
                      return <option key={s.name} value={s.name}>{fits ? '\u2713' : '\u26A0'} {s.name} ({adjCores}c / {adjRam}G)</option>;
                    })}
                  </select>
                  {node?.site_group && (
                    <span style={{ color: '#008e7a', fontSize: '0.85em', whiteSpace: 'nowrap' }} title="Co-location group from template">group: {node.site_group}</span>
                  )}
                </div>
              </div>
              <div className="form-group" data-help-id="editor.node.host">
                <label><Tooltip text="Pin VM to a specific physical host, or leave as auto">Host</Tooltip></label>
                <HostComboBox
                  hosts={hosts}
                  hostsLoading={hostsLoading}
                  value={host}
                  onChange={setHost}
                  disabled={!site || site === 'auto'}
                  cores={cores}
                  ram={ram}
                  disk={disk}
                  sliceData={sliceData}
                  excludeNodeName={node?.name}
                />
              </div>
              <div className="form-group" data-help-id="editor.node.cores">
                <label><Tooltip text="CPU cores (1-64)">Cores</Tooltip> <span className="range-value">{cores}</span></label>
                <input type="range" min={1} max={64} value={cores} onChange={(e) => setCores(+e.target.value)} />
              </div>
              <div className="form-group" data-help-id="editor.node.ram">
                <label><Tooltip text="RAM in GB (2-256)">RAM (GB)</Tooltip> <span className="range-value">{ram}</span></label>
                <input type="range" min={2} max={256} value={ram} onChange={(e) => setRam(+e.target.value)} />
              </div>
              <div className="form-group" data-help-id="editor.node.disk">
                <label><Tooltip text="Root disk in GB (10-500)">Disk (GB)</Tooltip> <span className="range-value">{disk}</span></label>
                <input type="range" min={10} max={500} value={disk} onChange={(e) => setDisk(+e.target.value)} />
              </div>
              <div className="form-group" data-help-id="editor.node.image">
                <label><Tooltip text="OS image or VM template">Image</Tooltip></label>
                <ImageComboBox
                  images={images}
                  vmTemplates={vmTemplates}
                  value={image}
                  onSelect={handleImageSelect}
                />
              </div>
              {appliedTemplateName && (
                <div style={{ fontSize: 10, color: 'var(--fabric-teal)', marginTop: -4, marginBottom: 4, paddingLeft: 2 }}>
                  VM template applied: {appliedTemplateName}
                </div>
              )}

              <div className="form-actions">
                <button
                  className="primary"
                  disabled={loading || !sliceName}
                  onClick={() => onSubmit({ site, host: host || '', cores, ram, disk, image })}
                >
                  Update Node
                </button>
                {onSaveVmTemplate && node && (
                  <Tooltip text="Save this node's image and boot config as a reusable VM template">
                    <button
                      disabled={loading}
                      onClick={() => onSaveVmTemplate(node.name)}
                      data-help-id="editor.node.vm-template"
                    >
                      Save VM Template
                    </button>
                  </Tooltip>
                )}
              </div>

              {onDelete && (
                <>
                  <div className="editor-section-divider" />
                  <button className="danger-btn" disabled={loading} onClick={onDelete}>
                    Delete Node
                  </button>
                </>
              )}
            </>
          )}
        </>
      )}

      {/* Components tab */}
      {nodeTab === 'components' && node && (
        <>
          {node.components.length === 0 ? (
            <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', fontStyle: 'italic', marginBottom: 8 }}>
              No components attached.
            </div>
          ) : (
            <div className="component-list">
              {node.components.map((comp) => (
                <div key={comp.name} className="component-row">
                  <span className="component-row-name">{comp.name}</span>
                  <span className="component-row-model">{comp.model}</span>
                  {!isLocked && (
                    <button
                      className="component-row-delete"
                      onClick={() => onDeleteComponent?.(comp.name)}
                      disabled={loading}
                      title={`Remove ${comp.name}`}
                    >
                      {'\u2715'}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {!isLocked && (
            <div className="form-group" style={{ marginTop: 8 }} data-help-id="editor.comp.model">
              <label><Tooltip text="Hardware type to attach">Add Component</Tooltip></label>
              <select value={compModel} onChange={(e) => {
                setCompModel(e.target.value);
                const curCompNames = node?.components.map((c) => c.name) ?? [];
                setCompName(nextName(compPrefix(e.target.value), curCompNames));
              }} style={{ marginBottom: 4 }}>
                {componentModels.map((c) => (
                  <option key={c.model} value={c.model}>{c.model} — {c.description}</option>
                ))}
              </select>
              <div style={{ display: 'flex', gap: 4 }}>
                <input
                  type="text"
                  value={compName}
                  onChange={(e) => setCompName(e.target.value)}
                  placeholder="nic1"
                  style={{ flex: 1 }}
                />
                <button
                  disabled={!compName || loading}
                  onClick={() => {
                    onAddComponent?.({ name: compName, model: compModel });
                    const updatedNames = [...(node?.components.map((c) => c.name) ?? []), compName];
                    setCompName(nextName(compPrefix(compModel), updatedNames));
                  }}
                >
                  Add
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Boot Config tab */}
      {nodeTab === 'boot' && node && (
        <BootConfigSection sliceName={sliceName} nodeName={node.name} loading={loading} isLocked={isLocked} isNodeActive={isNodeActive} />
      )}

      {/* Files tab (active nodes only) */}
      {nodeTab === 'files' && node && isNodeActive && (
        <FilesTab sliceName={sliceName} nodeName={node.name} />
      )}

      {/* Shell tab (active nodes only) */}
      {nodeTab === 'shell' && node && isNodeActive && (
        <ShellTab sliceName={sliceName} nodeName={node.name} />
      )}
    </>
  );
}


// --- Boot Config Section ---
function BootConfigSection({ sliceName, nodeName, loading: parentLoading, isLocked = false, isNodeActive = false }: {
  sliceName: string;
  nodeName: string;
  loading: boolean;
  isLocked?: boolean;
  isNodeActive?: boolean;
}) {
  const [bootConfig, setBootConfig] = useState<BootConfig | null>(null);
  const [dirty, setDirty] = useState(false);
  const [bootLoading, setBootLoading] = useState(false);
  const [bootError, setBootError] = useState('');
  const [execResults, setExecResults] = useState<BootExecResult[] | null>(null);

  // Upload add form
  const [newSource, setNewSource] = useState('');
  const [newDest, setNewDest] = useState('');

  // Command add form
  const [newCommand, setNewCommand] = useState('');

  // File picker
  const [showPicker, setShowPicker] = useState(false);
  const [pickerPath, setPickerPath] = useState('');
  const [pickerFiles, setPickerFiles] = useState<FileEntry[]>([]);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerSelected, setPickerSelected] = useState('');

  const loadBootConfig = useCallback(async () => {
    if (!sliceName || !nodeName) return;
    setBootLoading(true);
    setBootError('');
    try {
      const cfg = await api.getBootConfig(sliceName, nodeName);
      setBootConfig(cfg);
      setDirty(false);
      setExecResults(null);
    } catch (e: any) {
      // If no config exists yet, start with empty
      setBootConfig({ uploads: [], commands: [], network: [] });
      setDirty(false);
    } finally {
      setBootLoading(false);
    }
  }, [sliceName, nodeName]);

  // Load immediately when mounted or node changes
  useEffect(() => {
    setBootConfig(null);
    setDirty(false);
    setExecResults(null);
    loadBootConfig();
  }, [nodeName, loadBootConfig]);

  const genId = () => crypto.randomUUID?.() ?? Math.random().toString(36).slice(2, 10);

  // --- Upload management ---
  const addUpload = () => {
    if (!newSource || !newDest || !bootConfig) return;
    const upload: BootUpload = { id: genId(), source: newSource, dest: newDest };
    setBootConfig({ ...bootConfig, uploads: [...bootConfig.uploads, upload] });
    setNewSource('');
    setNewDest('');
    setDirty(true);
  };

  const removeUpload = (id: string) => {
    if (!bootConfig) return;
    setBootConfig({ ...bootConfig, uploads: bootConfig.uploads.filter((u) => u.id !== id) });
    setDirty(true);
  };

  // --- Command management ---
  const addCommand = () => {
    if (!newCommand || !bootConfig) return;
    const order = bootConfig.commands.length;
    const cmd: BootCommand = { id: genId(), command: newCommand, order };
    setBootConfig({ ...bootConfig, commands: [...bootConfig.commands, cmd] });
    setNewCommand('');
    setDirty(true);
  };

  const removeCommand = (id: string) => {
    if (!bootConfig) return;
    const cmds = bootConfig.commands.filter((c) => c.id !== id).map((c, i) => ({ ...c, order: i }));
    setBootConfig({ ...bootConfig, commands: cmds });
    setDirty(true);
  };

  const moveCommand = (id: string, dir: -1 | 1) => {
    if (!bootConfig) return;
    const cmds = [...bootConfig.commands];
    const idx = cmds.findIndex((c) => c.id === id);
    if (idx < 0) return;
    const newIdx = idx + dir;
    if (newIdx < 0 || newIdx >= cmds.length) return;
    [cmds[idx], cmds[newIdx]] = [cmds[newIdx], cmds[idx]];
    setBootConfig({ ...bootConfig, commands: cmds.map((c, i) => ({ ...c, order: i })) });
    setDirty(true);
  };

  // --- Save & Execute ---
  const handleSave = async () => {
    if (!bootConfig) return;
    setBootLoading(true);
    setBootError('');
    try {
      const saved = await api.saveBootConfig(sliceName, nodeName, bootConfig);
      setBootConfig(saved);
      setDirty(false);
    } catch (e: any) {
      setBootError(e.message);
    } finally {
      setBootLoading(false);
    }
  };

  const handleExecute = async () => {
    setBootLoading(true);
    setBootError('');
    setExecResults(null);
    try {
      // Save first if dirty
      if (dirty && bootConfig) {
        await api.saveBootConfig(sliceName, nodeName, bootConfig);
        setDirty(false);
      }
      const results = await api.executeBootConfig(sliceName, nodeName);
      setExecResults(results);
    } catch (e: any) {
      setBootError(e.message);
    } finally {
      setBootLoading(false);
    }
  };

  // --- File Picker ---
  const openPicker = async () => {
    setShowPicker(true);
    setPickerPath('');
    setPickerSelected('');
    setPickerLoading(true);
    try {
      const files = await api.listFiles('');
      setPickerFiles(files);
    } catch {
      setPickerFiles([]);
    } finally {
      setPickerLoading(false);
    }
  };

  const navigatePicker = async (dir: string) => {
    const newPath = pickerPath ? `${pickerPath}/${dir}` : dir;
    setPickerLoading(true);
    setPickerSelected('');
    try {
      const files = await api.listFiles(newPath);
      setPickerFiles(files);
      setPickerPath(newPath);
    } catch {
      setPickerFiles([]);
    } finally {
      setPickerLoading(false);
    }
  };

  const pickerGoUp = async () => {
    const parts = pickerPath.split('/').filter(Boolean);
    parts.pop();
    const newPath = parts.join('/');
    setPickerLoading(true);
    setPickerSelected('');
    try {
      const files = await api.listFiles(newPath);
      setPickerFiles(files);
      setPickerPath(newPath);
    } catch {
      setPickerFiles([]);
    } finally {
      setPickerLoading(false);
    }
  };

  const confirmPicker = () => {
    if (pickerSelected) {
      const fullPath = pickerPath ? `${pickerPath}/${pickerSelected}` : pickerSelected;
      setNewSource(fullPath);
    }
    setShowPicker(false);
  };

  const isLoading = parentLoading || bootLoading;

  return (
    <>
      {bootLoading && !bootConfig && (
        <div className="boot-empty">Loading boot config...</div>
      )}

      {bootConfig && (
        <>
          {bootError && (
            <div style={{ color: 'var(--fabric-coral)', fontSize: 11, marginBottom: 8 }}>{bootError}</div>
          )}

          {/* File Uploads */}
          <div className="boot-section" style={{ marginTop: 0, paddingTop: 0, borderTop: 'none' }}>
            <div className="boot-section-header">
              <span>File Uploads</span>
            </div>
            {bootConfig.uploads.length === 0 ? (
              <div className="boot-empty">No upload rules configured.</div>
            ) : (
              <div className="boot-uploads-table">
                {bootConfig.uploads.map((u) => (
                  <div key={u.id} className="boot-upload-row">
                    <span className="boot-upload-source" title={u.source}>{u.source}</span>
                    <span style={{ fontSize: 10, color: 'var(--fabric-text-muted)' }}>{'\u2192'}</span>
                    <span className="boot-upload-source" title={u.dest} style={{ color: 'var(--fabric-teal)' }}>{u.dest}</span>
                    {!isLocked && <button className="boot-btn-remove" onClick={() => removeUpload(u.id)} disabled={isLoading}>{'\u2715'}</button>}
                  </div>
                ))}
              </div>
            )}
            {/* Add upload row */}
            {!isLocked && (
              <div style={{ marginTop: 6 }}>
                <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
                  <input
                    type="text"
                    value={newSource}
                    onChange={(e) => setNewSource(e.target.value)}
                    placeholder="Source (container)"
                    style={{ flex: 1, fontSize: 11, padding: '3px 6px' }}
                  />
                  <button className="boot-btn-sm" onClick={openPicker} disabled={isLoading} title="Browse container storage">...</button>
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                  <input
                    type="text"
                    value={newDest}
                    onChange={(e) => setNewDest(e.target.value)}
                    placeholder="Dest (VM path)"
                    style={{ flex: 1, fontSize: 11, padding: '3px 6px' }}
                  />
                  <button className="boot-btn-sm" onClick={addUpload} disabled={isLoading || !newSource || !newDest}>Add</button>
                </div>
              </div>
            )}
          </div>

          {/* Post-Boot Commands */}
          <div className="boot-section">
            <div className="boot-section-header">
              <span>Post-Boot Commands</span>
            </div>
            {bootConfig.commands.length === 0 ? (
              <div className="boot-empty">No commands configured.</div>
            ) : (
              <div className="boot-commands-list">
                {bootConfig.commands.map((cmd, idx) => (
                  <div key={cmd.id} className="boot-command-row">
                    <input
                      className="boot-cmd-input"
                      type="text"
                      value={cmd.command}
                      readOnly
                    />
                    {!isLocked && (
                      <div className="boot-cmd-controls">
                        <button onClick={() => moveCommand(cmd.id, -1)} disabled={idx === 0 || isLoading} title="Move up">{'\u25B2'}</button>
                        <button onClick={() => moveCommand(cmd.id, 1)} disabled={idx === bootConfig.commands.length - 1 || isLoading} title="Move down">{'\u25BC'}</button>
                        <button className="boot-btn-remove" onClick={() => removeCommand(cmd.id)} disabled={isLoading}>{'\u2715'}</button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
            {/* Add command row */}
            {!isLocked && (
              <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
                <input
                  className="boot-cmd-input"
                  type="text"
                  value={newCommand}
                  onChange={(e) => setNewCommand(e.target.value)}
                  placeholder="Shell command..."
                  onKeyDown={(e) => { if (e.key === 'Enter') addCommand(); }}
                />
                <button className="boot-btn-sm" onClick={addCommand} disabled={isLoading || !newCommand}>Add</button>
              </div>
            )}
          </div>

          {/* Save & Execute */}
          <div className="boot-actions">
            {!isLocked && (
              <button
                className={dirty ? 'primary' : ''}
                disabled={isLoading || !dirty}
                onClick={handleSave}
              >
                {bootLoading ? 'Saving...' : 'Save'}
              </button>
            )}
            <button
              disabled={isLoading || !isNodeActive || (bootConfig.uploads.length === 0 && bootConfig.commands.length === 0)}
              onClick={handleExecute}
            >
              {bootLoading ? 'Running...' : 'Execute'}
            </button>
          </div>

          {/* Execution Results */}
          {execResults && (
            <div className="boot-results">
              {execResults.map((r) => (
                <div key={r.id} className={`boot-result-row ${r.status}`}>
                  <span className="boot-result-type">{r.type}</span>
                  <span className={`boot-result-status ${r.status}`}>{r.status}</span>
                  {r.detail && <span className="boot-result-detail">{r.detail}</span>}
                </div>
              ))}
            </div>
          )}

          {/* File Picker Modal */}
          {showPicker && (
            <div className="boot-file-picker-overlay" onClick={() => setShowPicker(false)}>
              <div className="boot-file-picker" onClick={(e) => e.stopPropagation()}>
                <div className="boot-fp-header">
                  <span>Select File or Folder</span>
                  <button onClick={() => setShowPicker(false)}>{'\u2715'}</button>
                </div>
                <div className="boot-fp-breadcrumb">
                  <button onClick={() => { setPickerPath(''); setPickerSelected(''); api.listFiles('').then(setPickerFiles); }}>root</button>
                  {pickerPath.split('/').filter(Boolean).map((seg, i, arr) => (
                    <span key={i}>
                      {' / '}
                      <button onClick={() => {
                        const p = arr.slice(0, i + 1).join('/');
                        setPickerPath(p);
                        setPickerSelected('');
                        api.listFiles(p).then(setPickerFiles);
                      }}>{seg}</button>
                    </span>
                  ))}
                </div>
                <div className="boot-fp-hint">
                  Click to select. Double-click folders to open.
                </div>
                <div className="boot-fp-list">
                  {pickerPath && (
                    <div className="boot-fp-entry" onClick={pickerGoUp}>
                      <span className="boot-fp-icon">{'\u2B06'}</span>
                      <span className="boot-fp-name">..</span>
                    </div>
                  )}
                  {pickerLoading ? (
                    <div className="boot-empty" style={{ padding: 20 }}>Loading...</div>
                  ) : pickerFiles.length === 0 ? (
                    <div className="boot-empty" style={{ padding: 20 }}>Empty directory</div>
                  ) : (
                    pickerFiles.map((f) => (
                      <div
                        key={f.name}
                        className={`boot-fp-entry ${pickerSelected === f.name ? 'selected' : ''}`}
                        onClick={() => setPickerSelected(f.name)}
                        onDoubleClick={() => {
                          if (f.type === 'dir') {
                            navigatePicker(f.name);
                          } else {
                            setPickerSelected(f.name);
                            const fullPath = pickerPath ? `${pickerPath}/${f.name}` : f.name;
                            setNewSource(fullPath);
                            setShowPicker(false);
                          }
                        }}
                      >
                        <span className="boot-fp-icon">{f.type === 'dir' ? '\uD83D\uDCC1' : '\uD83D\uDCC4'}</span>
                        <span className="boot-fp-name">{f.name}</span>
                        {f.type === 'file' ? (
                          <span className="boot-fp-size">{formatSize(f.size)}</span>
                        ) : (
                          <span className="boot-fp-size">folder</span>
                        )}
                      </div>
                    ))
                  )}
                </div>
                <div className="boot-fp-actions">
                  <button onClick={() => setShowPicker(false)}>Cancel</button>
                  <button className="primary" disabled={!pickerSelected} onClick={confirmPicker}>Select</button>
                </div>
              </div>
            </div>
          )}
        </>
      )}

    </>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}


// --- Files Tab (upload to VM) ---
function FilesTab({ sliceName, nodeName }: { sliceName: string; nodeName: string }) {
  const [source, setSource] = useState('');
  const [dest, setDest] = useState('');
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  // File picker state
  const [showPicker, setShowPicker] = useState(false);
  const [pickerPath, setPickerPath] = useState('');
  const [pickerFiles, setPickerFiles] = useState<FileEntry[]>([]);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerSelected, setPickerSelected] = useState('');

  const openPicker = async () => {
    setShowPicker(true);
    setPickerPath('');
    setPickerSelected('');
    setPickerLoading(true);
    try {
      const files = await api.listFiles('');
      setPickerFiles(files);
    } catch {
      setPickerFiles([]);
    } finally {
      setPickerLoading(false);
    }
  };

  const navigatePicker = async (dir: string) => {
    const newPath = pickerPath ? `${pickerPath}/${dir}` : dir;
    setPickerLoading(true);
    setPickerSelected('');
    try {
      const files = await api.listFiles(newPath);
      setPickerFiles(files);
      setPickerPath(newPath);
    } catch {
      setPickerFiles([]);
    } finally {
      setPickerLoading(false);
    }
  };

  const pickerGoUp = async () => {
    const parts = pickerPath.split('/').filter(Boolean);
    parts.pop();
    const newPath = parts.join('/');
    setPickerLoading(true);
    setPickerSelected('');
    try {
      const files = await api.listFiles(newPath);
      setPickerFiles(files);
      setPickerPath(newPath);
    } catch {
      setPickerFiles([]);
    } finally {
      setPickerLoading(false);
    }
  };

  const handleUpload = async () => {
    if (!source || !dest) return;
    setUploading(true);
    setResult(null);
    try {
      await api.uploadToVm(sliceName, nodeName, source, dest);
      setResult({ ok: true, message: `Uploaded ${source} to ${dest}` });
    } catch (e: any) {
      setResult({ ok: false, message: e.message });
    } finally {
      setUploading(false);
    }
  };

  return (
    <>
      <div className="editor-section-label">Upload to VM</div>

      <div className="form-group">
        <label style={{ fontSize: 11 }}>Source (container storage)</label>
        <div style={{ display: 'flex', gap: 4 }}>
          <input
            type="text"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="path/to/file"
            style={{ flex: 1, fontSize: 11, padding: '3px 6px' }}
          />
          <button className="boot-btn-sm" onClick={openPicker} disabled={uploading}>...</button>
        </div>
      </div>

      <div className="form-group">
        <label style={{ fontSize: 11 }}>Destination (VM path)</label>
        <input
          type="text"
          value={dest}
          onChange={(e) => setDest(e.target.value)}
          placeholder="/home/ubuntu/"
          style={{ fontSize: 11, padding: '3px 6px' }}
        />
      </div>

      <div className="form-actions">
        <button
          className="primary"
          disabled={uploading || !source || !dest}
          onClick={handleUpload}
        >
          {uploading ? 'Uploading...' : 'Upload'}
        </button>
      </div>

      {result && (
        <div style={{
          marginTop: 8,
          padding: '6px 8px',
          borderRadius: 4,
          fontSize: 11,
          background: result.ok ? 'rgba(0,142,122,0.1)' : 'rgba(226,82,65,0.1)',
          color: result.ok ? 'var(--fabric-teal)' : 'var(--fabric-coral)',
        }}>
          {result.message}
        </div>
      )}

      {/* File Picker Modal */}
      {showPicker && (
        <div className="boot-file-picker-overlay" onClick={() => setShowPicker(false)}>
          <div className="boot-file-picker" onClick={(e) => e.stopPropagation()}>
            <div className="boot-fp-header">
              <span>Select File or Folder</span>
              <button onClick={() => setShowPicker(false)}>{'\u2715'}</button>
            </div>
            <div className="boot-fp-breadcrumb">
              <button onClick={() => { setPickerPath(''); setPickerSelected(''); api.listFiles('').then(setPickerFiles); }}>root</button>
              {pickerPath.split('/').filter(Boolean).map((seg, i, arr) => (
                <span key={i}>
                  {' / '}
                  <button onClick={() => {
                    const p = arr.slice(0, i + 1).join('/');
                    setPickerPath(p);
                    setPickerSelected('');
                    api.listFiles(p).then(setPickerFiles);
                  }}>{seg}</button>
                </span>
              ))}
            </div>
            <div className="boot-fp-list">
              {pickerPath && (
                <div className="boot-fp-entry" onClick={pickerGoUp}>
                  <span className="boot-fp-icon">{'\u2B06'}</span>
                  <span className="boot-fp-name">..</span>
                </div>
              )}
              {pickerLoading ? (
                <div className="boot-empty" style={{ padding: 20 }}>Loading...</div>
              ) : pickerFiles.length === 0 ? (
                <div className="boot-empty" style={{ padding: 20 }}>Empty directory</div>
              ) : (
                pickerFiles.map((f) => (
                  <div
                    key={f.name}
                    className={`boot-fp-entry ${pickerSelected === f.name ? 'selected' : ''}`}
                    onClick={() => setPickerSelected(f.name)}
                    onDoubleClick={() => {
                      if (f.type === 'dir') {
                        navigatePicker(f.name);
                      } else {
                        const fullPath = pickerPath ? `${pickerPath}/${f.name}` : f.name;
                        setSource(fullPath);
                        setShowPicker(false);
                      }
                    }}
                  >
                    <span className="boot-fp-icon">{f.type === 'dir' ? '\uD83D\uDCC1' : '\uD83D\uDCC4'}</span>
                    <span className="boot-fp-name">{f.name}</span>
                    {f.type === 'file' ? (
                      <span className="boot-fp-size">{formatSize(f.size)}</span>
                    ) : (
                      <span className="boot-fp-size">folder</span>
                    )}
                  </div>
                ))
              )}
            </div>
            <div className="boot-fp-actions">
              <button onClick={() => setShowPicker(false)}>Cancel</button>
              <button className="primary" disabled={!pickerSelected} onClick={() => {
                const fullPath = pickerPath ? `${pickerPath}/${pickerSelected}` : pickerSelected;
                setSource(fullPath);
                setShowPicker(false);
              }}>Select</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}


// --- Shell Tab (execute commands on VM) ---
function ShellTab({ sliceName, nodeName }: { sliceName: string; nodeName: string }) {
  const [command, setCommand] = useState('');
  const [running, setRunning] = useState(false);
  const [output, setOutput] = useState<Array<{ cmd: string; stdout: string; stderr: string }>>([]);

  const handleRun = async () => {
    if (!command.trim()) return;
    setRunning(true);
    try {
      const result = await api.executeOnVm(sliceName, nodeName, command);
      setOutput((prev) => [...prev, { cmd: command, stdout: result.stdout, stderr: result.stderr }]);
      setCommand('');
    } catch (e: any) {
      setOutput((prev) => [...prev, { cmd: command, stdout: '', stderr: e.message }]);
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <div className="editor-section-label">Shell</div>

      <div className="form-group">
        <textarea
          className="shell-input"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          placeholder="Enter command..."
          rows={3}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              handleRun();
            }
          }}
        />
      </div>

      <div className="form-actions">
        <button
          className="primary"
          disabled={running || !command.trim()}
          onClick={handleRun}
        >
          {running ? 'Running...' : 'Run'}
        </button>
        {output.length > 0 && (
          <button onClick={() => setOutput([])} style={{ marginLeft: 4 }}>Clear</button>
        )}
      </div>

      {output.length > 0 && (
        <div className="shell-output-area">
          {output.map((entry, i) => (
            <div key={i} className="shell-entry">
              <div className="shell-cmd-line">$ {entry.cmd}</div>
              {entry.stdout && <pre className="shell-stdout">{entry.stdout}</pre>}
              {entry.stderr && <pre className="shell-stderr">{entry.stderr}</pre>}
            </div>
          ))}
        </div>
      )}
    </>
  );
}


// --- Network Form (add only) ---
function NetworkForm({
  mode, defaultLayer, sliceData, sliceName, loading, onSubmit,
}: {
  mode: 'add';
  defaultLayer: 'L2' | 'L3';
  sliceData: SliceData | null;
  sliceName: string;
  loading: boolean;
  onSubmit: (data: {
    name: string; type: string; interfaces: string[];
    subnet?: string; gateway?: string; ip_mode?: string;
    interface_ips?: Record<string, string>;
  }) => void;
}) {
  const defaultNetName = sliceData
    ? nextName('net', sliceData.networks.map((n) => n.name))
    : '';
  const [name, setName] = useState(defaultNetName);
  const [layer, setLayer] = useState<'L2' | 'L3'>(defaultLayer);
  const [netType, setNetType] = useState(defaultLayer === 'L2' ? 'L2Bridge' : 'IPv4');
  const [selectedIfaces, setSelectedIfaces] = useState<string[]>([]);
  const [subnet, setSubnet] = useState('');
  const [gateway, setGateway] = useState('');
  const [ipMode, setIpMode] = useState<'none' | 'auto' | 'config'>('none');
  const [interfaceIps, setInterfaceIps] = useState<Record<string, string>>({});

  const l2Types = ['L2Bridge', 'L2STS', 'L2PTP'];
  const l3Types = ['IPv4', 'IPv6', 'IPv4Ext', 'IPv6Ext'];
  const types = layer === 'L2' ? l2Types : l3Types;

  const allIfaces: string[] = [];
  for (const node of sliceData?.nodes ?? []) {
    for (const iface of node.interfaces) {
      if (!iface.network_name) {
        allIfaces.push(iface.name);
      }
    }
  }

  return (
    <>
      <div className="editor-section-label">Add {layer} Network</div>

      <div className="form-group" data-help-id="editor.net.name">
        <label><Tooltip text="Unique name for this network">Name</Tooltip></label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="net1" />
      </div>
      <div className="form-group" data-help-id="editor.net.layer">
        <label><Tooltip text="L2 = Ethernet switching. L3 = IP routed.">Layer</Tooltip></label>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['L2', 'L3'] as const).map((l) => (
            <button
              key={l}
              className={layer === l ? 'primary' : ''}
              style={{ flex: 1 }}
              onClick={() => {
                setLayer(l);
                setNetType(l === 'L2' ? 'L2Bridge' : 'IPv4');
                if (l === 'L3') {
                  setSubnet(''); setGateway(''); setIpMode('none'); setInterfaceIps({});
                }
              }}
            >
              {l}
            </button>
          ))}
        </div>
      </div>
      <div className="form-group" data-help-id="editor.net.type">
        <label><Tooltip text="Specific network service type">Type</Tooltip></label>
        <select value={netType} onChange={(e) => setNetType(e.target.value)}>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <div className="form-group" data-help-id="editor.net.interfaces">
        <label><Tooltip text="Select unattached NIC interfaces">Interfaces</Tooltip></label>
        <select
          multiple
          value={selectedIfaces}
          onChange={(e) => setSelectedIfaces(Array.from(e.target.selectedOptions, (o) => o.value))}
        >
          {allIfaces.map((i) => <option key={i} value={i}>{i}</option>)}
        </select>
        {allIfaces.length === 0 && (
          <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', marginTop: 4 }}>
            No unattached interfaces. Add components with NICs first.
          </div>
        )}
      </div>

      {layer === 'L3' && (
        <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', marginTop: 4, marginBottom: 8 }}>
          Subnet, gateway, and IPs are auto-assigned for L3 networks.
        </div>
      )}

      {layer === 'L2' && (
        <>
          <div className="form-group" data-help-id="editor.net.subnet">
            <label><Tooltip text="Optional CIDR subnet">Subnet (optional)</Tooltip></label>
            <input type="text" value={subnet} onChange={(e) => setSubnet(e.target.value)} placeholder="192.168.1.0/24" />
          </div>
          {subnet && (
            <>
              <div className="form-group" data-help-id="editor.net.gateway">
                <label><Tooltip text="Gateway IP within the subnet">Gateway (optional)</Tooltip></label>
                <input type="text" value={gateway} onChange={(e) => setGateway(e.target.value)} placeholder="192.168.1.1" />
              </div>
              <div className="form-group" data-help-id="editor.net.ip-mode">
                <label><Tooltip text="How IPs are assigned">IP Assignment</Tooltip></label>
                <select value={ipMode} onChange={(e) => setIpMode(e.target.value as 'none' | 'auto' | 'config')}>
                  <option value="none">None (configure after boot)</option>
                  <option value="auto">Auto (FABlib assigns)</option>
                  <option value="config">User-Defined (specify per interface)</option>
                </select>
              </div>
              {ipMode === 'config' && selectedIfaces.length > 0 && (
                <div className="form-group" data-help-id="editor.net.interface-ips">
                  <label><Tooltip text="Assign IP to each interface">Interface IPs</Tooltip></label>
                  {selectedIfaces.map((ifName) => (
                    <div key={ifName} style={{ display: 'flex', gap: 4, marginBottom: 4, alignItems: 'center' }}>
                      <span style={{ fontSize: 11, minWidth: 80 }}>{ifName}</span>
                      <input
                        type="text"
                        value={interfaceIps[ifName] || ''}
                        onChange={(e) => setInterfaceIps((prev) => ({ ...prev, [ifName]: e.target.value }))}
                        placeholder="10.0.0.1"
                        style={{ flex: 1 }}
                      />
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </>
      )}

      <div className="form-actions">
        <button
          className="primary"
          disabled={!name || loading}
          onClick={() => onSubmit({
            name,
            type: netType,
            interfaces: selectedIfaces,
            ...(layer === 'L2' && subnet ? { subnet, gateway: gateway || undefined, ip_mode: ipMode } : {}),
            ...(layer === 'L2' && ipMode === 'config' ? { interface_ips: interfaceIps } : {}),
          })}
        >
          Add Network
        </button>
      </div>
    </>
  );
}


// --- Facility Port Form (add only) ---
function FacilityPortForm({
  mode, sites, sliceName, loading, sliceData, onSubmit,
}: {
  mode: 'add';
  sites: SiteInfo[];
  sliceName: string;
  loading: boolean;
  sliceData?: SliceData | null;
  onSubmit: (data: { name: string; site: string; vlan?: string; bandwidth?: number }) => void;
}) {
  const defaultFpName = sliceData
    ? nextName('fp', (sliceData.facility_ports ?? []).map((f) => f.name))
    : '';
  const [name, setName] = useState(defaultFpName);
  const [site, setSite] = useState('');
  const [vlan, setVlan] = useState('');
  const [bandwidth, setBandwidth] = useState(10);

  return (
    <>
      <div className="editor-section-label">Add Facility Port</div>

      <div className="form-group" data-help-id="editor.facility-port">
        <label><Tooltip text="Unique name for this facility port">Name</Tooltip></label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="fp1" />
      </div>
      <div className="form-group">
        <label><Tooltip text="FABRIC site with the facility port">Site</Tooltip></label>
        <select value={site} onChange={(e) => setSite(e.target.value)}>
          <option value="">-- Select --</option>
          {sites.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
        </select>
      </div>
      <div className="form-group">
        <label><Tooltip text="VLAN ID for the external connection">VLAN</Tooltip></label>
        <input type="text" value={vlan} onChange={(e) => setVlan(e.target.value)} placeholder="100" />
      </div>
      <div className="form-group">
        <label><Tooltip text="Bandwidth in Gbps">Bandwidth (Gbps)</Tooltip> <span className="range-value">{bandwidth}</span></label>
        <input type="range" min={1} max={100} value={bandwidth} onChange={(e) => setBandwidth(+e.target.value)} />
      </div>

      <div className="form-actions">
        <button
          className="primary"
          disabled={!name || !site || !sliceName || loading}
          onClick={() => onSubmit({ name, site, vlan: vlan || undefined, bandwidth })}
        >
          Add Facility Port
        </button>
      </div>
    </>
  );
}


// --- L3 IP Hints Editor (FABNetv4/v6 networks) ---
type HintMode = 'auto' | 'fixed' | 'range';

const DEFAULT_L3_CONFIG: L3Config = {
  mode: 'auto',
  route_mode: 'default_fabnet',
  custom_routes: [],
  default_fabnet_subnet: '10.128.0.0/10',
};

function L3ConfigEditor({
  network, sliceName, isDraft, loading,
}: {
  network: SliceNetwork;
  sliceName: string;
  isDraft: boolean;
  loading: boolean;
}) {
  const [l3, setL3] = useState<L3Config>(network.l3_config || DEFAULT_L3_CONFIG);
  const [hints, setHints] = useState<Record<string, IpHint>>(network.ip_hints || {});
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState('');
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [newRoute, setNewRoute] = useState('');

  // Fetch L3 config from backend on mount/network change
  useEffect(() => {
    setL3(network.l3_config || DEFAULT_L3_CONFIG);
    setHints(network.ip_hints || {});
    setError('');
    setAssignments({});
    // Load saved L3 config from backend
    api.getL3Config(sliceName, network.name).then(r => {
      if (r.l3_config && Object.keys(r.l3_config).length > 0) setL3(r.l3_config as L3Config);
    }).catch(() => {});
    // Load saved IP hints from backend
    api.getIpHints(sliceName, network.name).then(r => {
      if (r.hints && Object.keys(r.hints).length > 0) setHints(r.hints);
    }).catch(() => {});
  }, [sliceName, network.name]);

  const setOctet = (iface: string, value: string) => {
    setHints(prev => {
      const next = { ...prev };
      const n = parseInt(value);
      next[iface] = { last_octet: isNaN(n) ? undefined : n };
      return next;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      await api.setL3Config(sliceName, network.name, l3);
      if (l3.mode === 'user_octet') {
        await api.setIpHints(sliceName, network.name, hints);
      }
    } catch (e: any) {
      setError(e.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleApply = async () => {
    setApplying(true);
    setError('');
    try {
      // Save first to ensure routes are stored
      await api.setL3Config(sliceName, network.name, l3);
      await api.setIpHints(sliceName, network.name, hints);
      const result = await api.applyIpHints(sliceName, network.name);
      setAssignments(result.assignments || {});
    } catch (e: any) {
      setError(e.message || 'Failed to apply');
    } finally {
      setApplying(false);
    }
  };

  const addCustomRoute = () => {
    const trimmed = newRoute.trim();
    if (!trimmed) return;
    setL3(prev => ({ ...prev, custom_routes: [...prev.custom_routes, trimmed] }));
    setNewRoute('');
  };

  const removeCustomRoute = (index: number) => {
    setL3(prev => ({ ...prev, custom_routes: prev.custom_routes.filter((_, i) => i !== index) }));
  };

  const hasSubnet = !!network.subnet;

  const modeButtonStyle = (active: boolean): React.CSSProperties => ({
    flex: 1,
    padding: '4px 6px',
    fontSize: '0.8em',
    border: `1px solid ${active ? 'var(--fabric-primary, #5798bc)' : 'var(--fabric-border, #ccc)'}`,
    borderRadius: 4,
    background: active ? 'var(--fabric-primary, #5798bc)' : 'transparent',
    color: active ? '#fff' : 'inherit',
    cursor: 'pointer',
  });

  return (
    <>
      {hasSubnet && (
        <>
          <div className="readonly-field">
            <span className="readonly-label">Subnet</span>
            <span className="readonly-value">{network.subnet}</span>
          </div>
          {network.gateway && (
            <div className="readonly-field">
              <span className="readonly-label">Gateway</span>
              <span className="readonly-value">{network.gateway}</span>
            </div>
          )}
        </>
      )}

      {!hasSubnet && isDraft && (
        <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', marginTop: 4, marginBottom: 8 }}>
          Subnet will be assigned by FABRIC at submit time.
        </div>
      )}

      {/* Section 1: Config Mode */}
      <div className="editor-section-divider" />
      <div className="editor-section-label">
        <Tooltip text="How IP addresses are assigned on this FABNet network">L3 Config Mode</Tooltip>
      </div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
        <button style={modeButtonStyle(l3.mode === 'auto')} onClick={() => setL3(prev => ({ ...prev, mode: 'auto' }))} disabled={loading}>
          Auto
        </button>
        <button style={modeButtonStyle(l3.mode === 'manual')} onClick={() => setL3(prev => ({ ...prev, mode: 'manual' }))} disabled={loading}>
          Manual
        </button>
        <button style={modeButtonStyle(l3.mode === 'user_octet')} onClick={() => setL3(prev => ({ ...prev, mode: 'user_octet' }))} disabled={loading}>
          User Octet
        </button>
      </div>
      <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', marginBottom: 8 }}>
        {l3.mode === 'auto' && 'FABLib automatically assigns IPs and configures routing.'}
        {l3.mode === 'manual' && 'No automatic configuration. Configure in boot scripts.'}
        {l3.mode === 'user_octet' && 'Choose last octet per interface. Works with /24 subnets.'}
      </div>

      {/* Section 2: Route Configuration (user_octet only) */}
      {l3.mode === 'user_octet' && (
        <>
          <div className="editor-section-divider" />
          <div className="editor-section-label">
            <Tooltip text="Subnet routes added to each interface after IP assignment">Route Configuration</Tooltip>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8, fontSize: '0.82em' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
              <input
                type="radio"
                name={`route-mode-${network.name}`}
                checked={l3.route_mode === 'default_fabnet'}
                onChange={() => setL3(prev => ({ ...prev, route_mode: 'default_fabnet' }))}
                disabled={loading}
              />
              Default FABNet Subnet
            </label>
            {l3.route_mode === 'default_fabnet' && (
              <div style={{ marginLeft: 22 }}>
                <input
                  type="text"
                  value={l3.default_fabnet_subnet}
                  onChange={(e) => setL3(prev => ({ ...prev, default_fabnet_subnet: e.target.value }))}
                  style={{ width: 140, fontSize: '0.95em' }}
                  placeholder="10.128.0.0/10"
                  disabled={loading}
                />
              </div>
            )}
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
              <input
                type="radio"
                name={`route-mode-${network.name}`}
                checked={l3.route_mode === 'custom'}
                onChange={() => setL3(prev => ({ ...prev, route_mode: 'custom' }))}
                disabled={loading}
              />
              Custom Subnets
            </label>
            {l3.route_mode === 'custom' && (
              <div style={{ marginLeft: 22 }}>
                {l3.custom_routes.map((route, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 2 }}>
                    <span style={{ flex: 1 }}>{route}</span>
                    <button
                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--fabric-coral, #e25241)', fontSize: 14 }}
                      onClick={() => removeCustomRoute(i)}
                      title="Remove route"
                      disabled={loading}
                    >
                      {'\u2715'}
                    </button>
                  </div>
                ))}
                <div style={{ display: 'flex', gap: 4, marginTop: 2 }}>
                  <input
                    type="text"
                    value={newRoute}
                    onChange={(e) => setNewRoute(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') addCustomRoute(); }}
                    placeholder="e.g. 10.128.0.0/10"
                    style={{ flex: 1, fontSize: '0.95em' }}
                    disabled={loading}
                  />
                  <button className="primary-btn" onClick={addCustomRoute} disabled={loading || !newRoute.trim()} style={{ fontSize: '0.85em', padding: '2px 8px' }}>
                    Add
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Section 3: Per-Interface Octets */}
          {network.interfaces.length > 0 && (
            <>
              <div className="editor-section-divider" />
              <div className="editor-section-label">
                <Tooltip text="Set the last octet (1-254) for each interface's IP address">Per-Interface Octets</Tooltip>
              </div>
              {network.interfaces.map((iface) => {
                const h = hints[iface.name];
                const assigned = assignments[iface.name];
                return (
                  <div key={iface.name} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, fontSize: '0.82em' }}>
                    <span style={{ minWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={iface.name}>
                      {iface.name}
                    </span>
                    <input
                      type="number"
                      min={1}
                      max={254}
                      value={h?.last_octet ?? ''}
                      onChange={(e) => setOctet(iface.name, e.target.value)}
                      style={{ width: 56, fontSize: '0.95em' }}
                      placeholder="1-254"
                      disabled={loading}
                    />
                    {assigned && (
                      <span style={{ color: 'var(--fabric-teal, #008e7a)', fontWeight: 600 }}>{assigned}</span>
                    )}
                    {!assigned && iface.ip_addr && (
                      <span style={{ color: 'var(--fabric-text-muted)' }}>{iface.ip_addr}</span>
                    )}
                  </div>
                );
              })}
            </>
          )}
        </>
      )}

      {error && <div className="form-error" style={{ marginTop: 4 }}>{error}</div>}

      <div style={{ display: 'flex', gap: 6, marginTop: 6, marginBottom: 8 }}>
        <button
          className="primary-btn"
          disabled={saving || loading}
          onClick={handleSave}
          style={{ flex: 1 }}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        {hasSubnet && l3.mode === 'user_octet' && (
          <button
            className="primary-btn"
            disabled={applying || loading}
            onClick={handleApply}
            style={{ flex: 1 }}
          >
            {applying ? 'Applying…' : 'Apply'}
          </button>
        )}
      </div>
    </>
  );
}


// --- Network read-only view (existing networks) ---
function NetworkReadOnlyView({
  network, loading, isDraft, sliceName, onSliceUpdated, onDelete,
}: {
  network: SliceNetwork;
  loading: boolean;
  isDraft: boolean;
  sliceName: string;
  onSliceUpdated: (data: SliceData) => void;
  onDelete: () => void;
}) {
  // Derive current IP mode from interface modes
  const modes = network.interfaces.map(i => i.mode).filter(Boolean);
  const derivedMode: 'none' | 'auto' | 'config' =
    modes.length === 0 ? 'none'
    : modes.every(m => m === 'auto') ? 'auto'
    : modes.some(m => m === 'config') ? 'config'
    : 'none';

  const [ipMode, setIpMode] = useState<'none' | 'auto' | 'config'>(derivedMode);
  const [subnet, setSubnet] = useState(network.subnet || '');
  const [gateway, setGateway] = useState(network.gateway || '');
  const [interfaceIps, setInterfaceIps] = useState<Record<string, string>>(() => {
    const ips: Record<string, string> = {};
    for (const iface of network.interfaces) {
      if (iface.ip_addr) ips[iface.name] = iface.ip_addr;
    }
    return ips;
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Reset local state when selected network changes
  useEffect(() => {
    const m = network.interfaces.map(i => i.mode).filter(Boolean);
    const dm: 'none' | 'auto' | 'config' =
      m.length === 0 ? 'none'
      : m.every(v => v === 'auto') ? 'auto'
      : m.some(v => v === 'config') ? 'config'
      : 'none';
    setIpMode(dm);
    setSubnet(network.subnet || '');
    setGateway(network.gateway || '');
    const ips: Record<string, string> = {};
    for (const iface of network.interfaces) {
      if (iface.ip_addr) ips[iface.name] = iface.ip_addr;
    }
    setInterfaceIps(ips);
    setError('');
  }, [network.name, network.subnet, network.gateway, network.interfaces]);

  const hasChanges = ipMode !== derivedMode || subnet !== (network.subnet || '') || gateway !== (network.gateway || '');

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      const result = await api.updateNetwork(sliceName, network.name, {
        subnet: subnet || undefined,
        gateway: gateway || undefined,
        ip_mode: ipMode,
        ...(ipMode === 'config' ? { interface_ips: interfaceIps } : {}),
      });
      onSliceUpdated(result);
    } catch (e: any) {
      setError(e.message || 'Failed to update network');
    } finally {
      setSaving(false);
    }
  };

  const isL2 = network.layer === 'L2';
  const canEdit = isDraft && isL2;

  return (
    <>
      <div className="editor-section-label">Network: {network.name}</div>

      <div className="readonly-field">
        <span className="readonly-label">Type</span>
        <span className="readonly-value">{network.type}</span>
      </div>
      <div className="readonly-field">
        <span className="readonly-label">Layer</span>
        <span className="readonly-value">{network.layer}</span>
      </div>

      {isL2 && canEdit ? (
        <>
          <div className="form-group" data-help-id="editor.net.ip-mode">
            <label><Tooltip text="How IPs are assigned to interfaces">IP Mode</Tooltip></label>
            <select value={ipMode} onChange={(e) => setIpMode(e.target.value as 'none' | 'auto' | 'config')}>
              <option value="none">None (configure after boot)</option>
              <option value="auto">Auto (FABlib assigns)</option>
              <option value="config">User-Defined (specify per interface)</option>
            </select>
          </div>

          {(ipMode === 'auto' || ipMode === 'config') && (
            <>
              <div className="form-group">
                <label><Tooltip text="CIDR subnet for the network">Subnet</Tooltip></label>
                <input type="text" value={subnet} onChange={(e) => setSubnet(e.target.value)} placeholder="e.g. 192.168.1.0/24" />
              </div>
              <div className="form-group">
                <label><Tooltip text="Optional gateway address">Gateway</Tooltip></label>
                <input type="text" value={gateway} onChange={(e) => setGateway(e.target.value)} placeholder="optional" />
              </div>
            </>
          )}

          {ipMode === 'config' && network.interfaces.length > 0 && (
            <div className="form-group" data-help-id="editor.net.interface-ips">
              <label><Tooltip text="Assign IP to each interface">Interface IPs</Tooltip></label>
              {network.interfaces.map((iface) => (
                <div key={iface.name} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <span style={{ fontSize: '0.82em', minWidth: 100 }}>{iface.name}</span>
                  <input
                    type="text"
                    value={interfaceIps[iface.name] || ''}
                    onChange={(e) => setInterfaceIps(prev => ({ ...prev, [iface.name]: e.target.value }))}
                    placeholder="e.g. 192.168.1.1"
                    style={{ flex: 1 }}
                  />
                </div>
              ))}
            </div>
          )}

          {error && <div className="form-error">{error}</div>}

          <button
            className="primary-btn"
            disabled={saving || loading}
            onClick={handleSave}
            style={{ marginTop: 4, marginBottom: 8 }}
          >
            {saving ? 'Saving…' : 'Apply IP Settings'}
          </button>
        </>
      ) : isL2 ? (
        <>
          <div className="readonly-field">
            <span className="readonly-label">IP Mode</span>
            <span className="readonly-value">{derivedMode === 'auto' ? 'Auto' : derivedMode === 'config' ? 'User-Defined' : 'None'}</span>
          </div>
          {network.subnet && (
            <div className="readonly-field">
              <span className="readonly-label">Subnet</span>
              <span className="readonly-value">{network.subnet}</span>
            </div>
          )}
          {network.gateway && (
            <div className="readonly-field">
              <span className="readonly-label">Gateway</span>
              <span className="readonly-value">{network.gateway}</span>
            </div>
          )}
        </>
      ) : (
        <L3ConfigEditor
          network={network}
          sliceName={sliceName}
          isDraft={isDraft}
          loading={loading}
        />
      )}

      {network.interfaces.length > 0 && network.layer === 'L2' && (
        <>
          <div className="editor-section-divider" />
          <div className="editor-section-label">Interfaces</div>
          {network.interfaces.map((iface) => (
            <div key={iface.name} className="readonly-field">
              <span className="readonly-label">{iface.name}</span>
              <span className="readonly-value">
                {iface.node_name}
                {iface.mode ? ` [${iface.mode}]` : ''}
                {iface.ip_addr ? ` ${iface.ip_addr}` : ''}
              </span>
            </div>
          ))}
        </>
      )}

      <div className="editor-section-divider" />
      <button className="danger-btn" disabled={loading} onClick={onDelete}>
        Delete Network
      </button>
    </>
  );
}


// --- Facility Port read-only view ---
function FacilityPortReadOnlyView({
  fp, loading, onDelete,
}: {
  fp: SliceFacilityPort;
  loading: boolean;
  onDelete: () => void;
}) {
  return (
    <>
      <div className="editor-section-label">Facility Port: {fp.name}</div>

      <div className="readonly-field">
        <span className="readonly-label">Site</span>
        <span className="readonly-value">{fp.site}</span>
      </div>
      {fp.vlan && (
        <div className="readonly-field">
          <span className="readonly-label">VLAN</span>
          <span className="readonly-value">{fp.vlan}</span>
        </div>
      )}
      {fp.bandwidth && (
        <div className="readonly-field">
          <span className="readonly-label">Bandwidth</span>
          <span className="readonly-value">{fp.bandwidth}</span>
        </div>
      )}

      {fp.interfaces.length > 0 && (
        <>
          <div className="editor-section-divider" />
          <div className="editor-section-label">Interfaces</div>
          {fp.interfaces.map((iface) => (
            <div key={iface.name} className="readonly-field">
              <span className="readonly-label">{iface.name}</span>
              <span className="readonly-value">{iface.network_name || '(unconnected)'}</span>
            </div>
          ))}
        </>
      )}

      <div className="editor-section-divider" />
      <button className="danger-btn" disabled={loading} onClick={onDelete}>
        Delete Facility Port
      </button>
    </>
  );
}
