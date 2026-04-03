'use client';
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import TestbedViewShell, { CHAMELEON_THEME } from './TestbedViewShell';
import type { Tab } from './TestbedViewShell';
import * as api from '../api/client';
import type { ChameleonLease, ChameleonInstance, ChameleonSite, ChameleonNetwork, ChameleonNodeTypeDetail } from '../types/chameleon';
import ChameleonTableView from './ChameleonTableView';
import ChameleonCalendar from './ChameleonCalendar';
import ChameleonEditor from './ChameleonEditor';
import dynamic from 'next/dynamic';
import '../styles/chameleon-view.css';

const GeoView = dynamic(() => import('./GeoView'), { ssr: false });

// Status badge CSS class
function statusClass(status: string): string {
  const s = status.toUpperCase();
  if (s === 'ACTIVE') return 'chi-status-active';
  if (s === 'PENDING' || s === 'STARTING') return 'chi-status-pending';
  if (s === 'BUILD') return 'chi-status-pending';
  if (s === 'ERROR') return 'chi-status-error';
  if (s === 'TERMINATED' || s === 'SHUTOFF' || s === 'DELETED') return 'chi-status-terminated';
  return '';
}

function formatDate(d: string): string {
  if (!d) return '';
  return d.replace('T', ' ').slice(0, 16);
}

interface ChameleonViewProps {
  onError?: (msg: string) => void;
  forcedTab?: string;  // When set, use this tab instead of internal state
  hideBar?: boolean;   // When true, don't render TestbedViewShell header/tabs
  onOpenTerminal?: (instance: { id: string; name: string; site: string }) => void;
}

export default function ChameleonView({ onError, forcedTab, hideBar, onOpenTerminal }: ChameleonViewProps) {
  const [sites, setSites] = useState<ChameleonSite[]>([]);
  const [leases, setLeases] = useState<ChameleonLease[]>([]);
  const [instances, setInstances] = useState<ChameleonInstance[]>([]);
  const [networks, setNetworks] = useState<ChameleonNetwork[]>([]);
  const [loading, setLoading] = useState(true);
  const [tabInternal, setTabInternal] = useState<'leases' | 'topology' | 'slices' | 'map' | 'resources' | 'calendar'>('leases');
  const tab = (forcedTab || tabInternal) as typeof tabInternal;
  const setTab = setTabInternal;
  const [chiAutoRefresh, setChiAutoRefresh] = useState(true);
  const [resourceCat, setResourceCat] = useState<'sites' | 'node-types' | 'networks'>('sites');
  const [selectedLease, setSelectedLease] = useState<ChameleonLease | null>(null);
  const [error, setError] = useState('');

  // Instance action loading state: { [instanceId]: 'reboot' | 'stop' | ... }
  const [actionLoading, setActionLoading] = useState<Record<string, string>>({});

  // Lease extend state
  const [extendHours, setExtendHours] = useState(4);
  const [extendLoading, setExtendLoading] = useState(false);
  const [deleteLeaseLoading, setDeleteLeaseLoading] = useState(false);

  // Create Lease modal state
  const [showCreateLease, setShowCreateLease] = useState(false);
  const [createSite, setCreateSite] = useState('CHI@TACC');
  const [createName, setCreateName] = useState('');
  const [createNodeType, setCreateNodeType] = useState('');
  const [createCount, setCreateCount] = useState(1);
  const [createHours, setCreateHours] = useState(4);
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [createError, setCreateError] = useState('');
  const [nodeTypes, setNodeTypes] = useState<Array<{ node_type: string; total: number; reservable: number; cpu_arch: string }>>([]);
  const [nodeTypesLoading, setNodeTypesLoading] = useState(false);
  // Future reservation
  const [startNow, setStartNow] = useState(true);
  const [createStartDate, setCreateStartDate] = useState('');
  // Resource type
  const [resourceType, setResourceType] = useState('physical:host');
  const [networkName, setNetworkName] = useState('');
  // Availability finder
  const [availResult, setAvailResult] = useState<{ earliest_start: string | null; available_now: number; total: number; error: string } | null>(null);
  const [availLoading, setAvailLoading] = useState(false);

  // Network creation state
  const [showCreateNetwork, setShowCreateNetwork] = useState(false);
  const [newNetName, setNewNetName] = useState('');
  const [newNetCidr, setNewNetCidr] = useState('192.168.1.0/24');
  const [newNetSite, setNewNetSite] = useState('');
  const [createNetLoading, setCreateNetLoading] = useState(false);

  // Confirmation modal state (replaces window.confirm)
  const [confirmAction, setConfirmAction] = useState<{ title: string; message: string; onConfirm: () => void; danger?: boolean } | null>(null);

  // Browse detailed node types per site
  const [detailedNodeTypes, setDetailedNodeTypes] = useState<Record<string, ChameleonNodeTypeDetail[]>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [s, l, i, n] = await Promise.all([
        api.getChameleonSites(),
        api.listChameleonLeases(),
        api.listChameleonInstances(),
        api.listChameleonNetworks().catch(() => [] as ChameleonNetwork[]),
      ]);
      setSites(s);
      setLeases(l);
      setInstances(i);
      setNetworks(n);
    } catch (e: any) {
      const msg = e.message || 'Failed to load Chameleon data';
      setError(msg);
      onError?.(msg);
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => { refresh(); }, [refresh]);

  // Poll every 30s (toggle-able)
  useEffect(() => {
    if (!chiAutoRefresh) return;
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
  }, [chiAutoRefresh, refresh]);

  // Fetch node types when create modal opens or site changes
  useEffect(() => {
    if (!showCreateLease || !createSite) return;
    setNodeTypesLoading(true);
    api.getChameleonNodeTypes(createSite)
      .then(data => {
        setNodeTypes(data.node_types || []);
        if (data.node_types?.length && !createNodeType) {
          setCreateNodeType(data.node_types[0].node_type);
        }
      })
      .catch(() => setNodeTypes([]))
      .finally(() => setNodeTypesLoading(false));
  }, [showCreateLease, createSite]);

  // Fetch detailed node types per configured site when resources/node-types active
  useEffect(() => {
    if (!(tab === 'resources' && resourceCat === 'node-types')) return;
    const configuredSites = sites.filter(s => s.configured);
    if (configuredSites.length === 0) return;
    configuredSites.forEach(s => {
      api.getChameleonNodeTypesDetail(s.name)
        .then(data => {
          setDetailedNodeTypes(prev => ({ ...prev, [s.name]: data.node_types || [] }));
        })
        .catch(() => {
          // Fall back: try regular node types
          api.getChameleonNodeTypes(s.name)
            .then(data => {
              const mapped: ChameleonNodeTypeDetail[] = (data.node_types || []).map(nt => ({
                node_type: nt.node_type,
                total: nt.total,
                reservable: nt.reservable,
                cpu_arch: nt.cpu_arch,
              }));
              setDetailedNodeTypes(prev => ({ ...prev, [s.name]: mapped }));
            })
            .catch(() => {});
        });
    });
  }, [tab, sites]);

  // Also fetch detailed node types for the create-lease modal (for richer dropdown)
  const [detailedCreateNodeTypes, setDetailedCreateNodeTypes] = useState<ChameleonNodeTypeDetail[]>([]);
  useEffect(() => {
    if (!showCreateLease || !createSite) return;
    api.getChameleonNodeTypesDetail(createSite)
      .then(data => setDetailedCreateNodeTypes(data.node_types || []))
      .catch(() => setDetailedCreateNodeTypes([]));
  }, [showCreateLease, createSite]);

  const handleFindAvailability = useCallback(async () => {
    if (!createNodeType || resourceType !== 'physical:host') return;
    setAvailLoading(true);
    setAvailResult(null);
    try {
      const result = await api.findChameleonAvailability({
        site: createSite,
        node_type: createNodeType,
        node_count: createCount,
        duration_hours: createHours,
      });
      setAvailResult(result);
      if (result.earliest_start && result.earliest_start !== 'now') {
        setStartNow(false);
        setCreateStartDate(result.earliest_start);
      }
    } catch (e: any) {
      setAvailResult({ earliest_start: null, available_now: 0, total: 0, error: e.message });
    } finally {
      setAvailLoading(false);
    }
  }, [createSite, createNodeType, createCount, createHours, resourceType]);

  const handleCreateLease = useCallback(async () => {
    if (!createName.trim()) { setCreateError('Name is required'); return; }
    if (resourceType === 'physical:host' && !createNodeType) { setCreateError('Select a node type'); return; }
    setCreateSubmitting(true);
    setCreateError('');
    try {
      const params: any = {
        site: createSite,
        name: createName.trim(),
        node_type: createNodeType,
        node_count: createCount,
        duration_hours: createHours,
        resource_type: resourceType,
      };
      if (!startNow && createStartDate) {
        params.start_date = createStartDate;
      }
      if (resourceType === 'network') {
        params.network_name = networkName || `${createName.trim()}-net`;
      }
      await api.createChameleonLease(params);
      setShowCreateLease(false);
      setCreateName('');
      setCreateNodeType('');
      setCreateCount(1);
      setCreateHours(4);
      setStartNow(true);
      setCreateStartDate('');
      setResourceType('physical:host');
      setAvailResult(null);
      refresh();
    } catch (e: any) {
      setCreateError(e.message || 'Failed to create lease');
    } finally {
      setCreateSubmitting(false);
    }
  }, [createSite, createName, createNodeType, createCount, createHours, refresh]);

  // Instance actions: reboot, stop, start, delete
  const handleInstanceAction = useCallback(async (
    instanceId: string, site: string,
    action: 'reboot' | 'stop' | 'start' | 'delete' | 'ssh' | string
  ) => {
    if (action === 'ssh') {
      const inst = instances.find(i => i.id === instanceId);
      if (!inst) return;
      if (onOpenTerminal) {
        onOpenTerminal({ id: inst.id, name: inst.name, site: inst.site });
      } else {
        // Fallback: popout window if no terminal handler
        const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/terminal/chameleon/${inst.id}?site=${encodeURIComponent(inst.site)}`;
        window.open(`/popout?tool=terminal&ws=${encodeURIComponent(wsUrl)}&title=${encodeURIComponent(`SSH: ${inst.name}`)}`, '_blank');
      }
      return;
    }
    const doAction = async () => {
      setActionLoading(prev => ({ ...prev, [instanceId]: action }));
      try {
        if (action === 'reboot') await api.rebootChameleonInstance(instanceId, site);
        else if (action === 'stop') await api.stopChameleonInstance(instanceId, site);
        else if (action === 'start') await api.startChameleonInstance(instanceId, site);
        else if (action === 'delete') await api.deleteChameleonInstance(instanceId, site);
        setTimeout(refresh, 2000);
      } catch (e: any) {
        onError?.(e.message || `Failed to ${action} instance`);
      } finally {
        setActionLoading(prev => { const n = { ...prev }; delete n[instanceId]; return n; });
      }
    };
    if (action === 'delete') {
      const inst = instances.find(i => i.id === instanceId);
      setConfirmAction({ title: 'Delete Instance', message: `Delete instance "${inst?.name || instanceId}"? This cannot be undone.`, onConfirm: doAction, danger: true });
      return;
    }
    if (action === 'reboot') {
      const inst = instances.find(i => i.id === instanceId);
      setConfirmAction({ title: 'Reboot Instance', message: `Reboot instance "${inst?.name || instanceId}"?`, onConfirm: doAction });
      return;
    }
    doAction();
  }, [instances, refresh, onError]);

  // Disassociate floating IP
  const handleDisassociateIp = useCallback(async (instanceId: string, site: string, floatingIp: string) => {
    setConfirmAction({
      title: 'Remove Floating IP',
      message: `Remove floating IP ${floatingIp}?`,
      onConfirm: async () => {
        setActionLoading(prev => ({ ...prev, [instanceId]: 'disassociate' }));
        try {
          await api.disassociateChameleonIp(instanceId, site, floatingIp);
          setTimeout(refresh, 2000);
        } catch (e: any) {
          onError?.(e.message || 'Failed to disassociate IP');
        } finally {
          setActionLoading(prev => { const n = { ...prev }; delete n[instanceId]; return n; });
        }
      },
    });
  }, [refresh, onError]);

  // Extend lease
  const handleExtendLease = useCallback(async () => {
    if (!selectedLease) return;
    setExtendLoading(true);
    try {
      await api.extendChameleonLease(selectedLease.id, selectedLease._site, extendHours);
      refresh();
    } catch (e: any) {
      onError?.(e.message || 'Failed to extend lease');
    } finally {
      setExtendLoading(false);
    }
  }, [selectedLease, extendHours, refresh, onError]);

  // Delete lease
  const handleDeleteLease = useCallback(async () => {
    if (!selectedLease) return;
    setConfirmAction({
      title: 'Delete Lease',
      message: `Delete lease "${selectedLease.name}"? This cannot be undone.`,
      danger: true,
      onConfirm: async () => {
        setDeleteLeaseLoading(true);
        try {
          await api.deleteChameleonLease(selectedLease.id, selectedLease._site);
          setSelectedLease(null);
          refresh();
        } catch (e: any) {
          onError?.(e.message || 'Failed to delete lease');
        } finally {
          setDeleteLeaseLoading(false);
        }
      },
    });
  }, [selectedLease, refresh, onError]);

  // Create network
  const handleCreateNetwork = useCallback(async () => {
    if (!newNetName.trim() || !newNetSite) return;
    setCreateNetLoading(true);
    try {
      await api.createChameleonNetwork({ site: newNetSite, name: newNetName.trim(), cidr: newNetCidr || undefined });
      setShowCreateNetwork(false);
      setNewNetName('');
      setNewNetCidr('192.168.1.0/24');
      refresh();
    } catch (e: any) {
      onError?.(e.message || 'Failed to create network');
    } finally {
      setCreateNetLoading(false);
    }
  }, [newNetName, newNetSite, newNetCidr, refresh, onError]);

  // Delete network
  const handleDeleteNetwork = useCallback((networkId: string, site: string) => {
    setConfirmAction({
      title: 'Delete Network',
      message: 'Delete this network? This cannot be undone.',
      danger: true,
      onConfirm: async () => {
        try {
          await api.deleteChameleonNetwork(networkId, site);
          refresh();
        } catch (e: any) {
          onError?.(e.message || 'Failed to delete network');
        }
      },
    });
  }, [refresh, onError]);

  // Grouped leases for the selector and lists
  const activeLeases = useMemo(() => leases.filter(l => l.status === 'ACTIVE'), [leases]);
  const pendingLeases = useMemo(() => leases.filter(l => l.status === 'PENDING'), [leases]);
  const pastLeases = useMemo(() => leases.filter(l => l.status !== 'ACTIVE' && l.status !== 'PENDING'), [leases]);

  // Build tabs for the shell — mirrors FABRIC view pattern
  const tabs: Tab[] = useMemo(() => [
    ...(selectedLease ? [{ id: 'topology', label: 'Topology' }] : []),
    { id: 'slices', label: 'Slices', badge: instances.length || undefined },
    { id: 'map', label: 'Map' },
    { id: 'calendar', label: 'Calendar' },
  ], [instances.length, selectedLease]);

  // Helper: get detail info for a node type in the create-lease dropdown
  const getDetailForNodeType = useCallback((nt: string): ChameleonNodeTypeDetail | undefined => {
    return detailedCreateNodeTypes.find(d => d.node_type === nt);
  }, [detailedCreateNodeTypes]);

  // Lease selector toolbar content
  const toolbarContent = (
    <div className="testbed-lease-selector">
      <select
        value={selectedLease?.id || ''}
        onChange={(e) => {
          const id = e.target.value;
          if (!id) {
            setSelectedLease(null);
          } else {
            const lease = leases.find(l => l.id === id);
            if (lease) setSelectedLease(lease);
          }
        }}
        title="Select active lease"
      >
        <option value="">-- No lease selected --</option>
        {activeLeases.length > 0 && (
          <optgroup label="Active">
            {activeLeases.map(l => (
              <option key={l.id} value={l.id}>{l.name} ({l._site})</option>
            ))}
          </optgroup>
        )}
        {pendingLeases.length > 0 && (
          <optgroup label="Pending">
            {pendingLeases.map(l => (
              <option key={l.id} value={l.id}>{l.name} ({l._site})</option>
            ))}
          </optgroup>
        )}
        {pastLeases.length > 0 && (
          <optgroup label="Past">
            {pastLeases.slice(0, 10).map(l => (
              <option key={l.id} value={l.id}>{l.name} ({l._site})</option>
            ))}
          </optgroup>
        )}
      </select>
      <button
        className="chi-create-btn"
        onClick={() => setShowCreateLease(true)}
        title="Create new lease"
      >
        + Lease
      </button>
      <button
        className="chi-refresh"
        onClick={refresh}
        disabled={loading}
        title="Refresh"
      >
        {loading ? '\u23F3' : '\u21BB'}
      </button>

      {/* New — open create lease modal */}
      <button
        className="chi-action-btn"
        onClick={() => setShowCreateLease(true)}
        title="Create a new Chameleon lease"
      >+ New</button>

      {/* Submit — deploy instances on active lease */}
      <button
        className="chi-action-btn"
        disabled={!selectedLease || selectedLease.status !== 'ACTIVE'}
        onClick={() => {
          if (selectedLease) setTab('topology');
        }}
        title="Deploy instances on the selected lease"
      >Submit</button>

      {/* Delete lease */}
      <button
        className="chi-action-btn chi-action-danger"
        disabled={!selectedLease}
        onClick={() => {
          if (!selectedLease) return;
          setConfirmAction({ title: 'Delete Lease', message: `Delete lease "${selectedLease.name}"? This cannot be undone.`, danger: true, onConfirm: async () => {
            try {
              await api.deleteChameleonLease(selectedLease.id, selectedLease._site);
              setSelectedLease(null);
              refresh();
            } catch (e: any) { onError?.(e.message); }
          }});
        }}
        title="Delete selected lease"
      >Delete</button>

      {/* Auto-refresh toggle */}
      <button
        className={`chi-action-btn ${chiAutoRefresh ? 'chi-action-active' : ''}`}
        onClick={() => setChiAutoRefresh(prev => !prev)}
        title={chiAutoRefresh ? 'Disable auto-refresh' : 'Enable auto-refresh'}
      >
        {chiAutoRefresh ? '\u25CF Auto: ON' : '\u25CB Auto: OFF'}
      </button>
    </div>
  );

  const content = (
    <>
      {error && <div className="chi-error">{error}</div>}

      {tab === 'topology' && (
        <ChameleonEditor
          sites={sites}
          onError={onError}
          onDeployed={(leaseId) => { refresh(); setTab('slices'); }}
          graphOnly
        />
      )}

      {/* Leases tab removed — use OpenStack tab */}
      {false && tab === 'leases' && (
        <div className="chi-content">
          {activeLeases.length > 0 && (
            <>
              <h3 className="chi-section-title">Active Leases</h3>
              <div className="chi-lease-list">
                {activeLeases.map(l => (
                  <div key={l.id} className={`chi-lease-card${selectedLease?.id === l.id ? ' selected' : ''}`}
                    onClick={() => setSelectedLease(l)}>
                    <div className="chi-lease-header">
                      <span className="chi-lease-name">{l.name}</span>
                      <span className={`chi-status ${statusClass(l.status)}`}>{l.status}</span>
                    </div>
                    <div className="chi-lease-meta">
                      <span>{l._site}</span>
                      <span>{formatDate(l.start_date)} → {formatDate(l.end_date)}</span>
                    </div>
                    {l.reservations.length > 0 && (
                      <div className="chi-lease-reservations">
                        {l.reservations.map(r => (
                          <span key={r.id} className="chi-reservation">
                            {r.resource_type} ({r.min}-{r.max})
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          {pendingLeases.length > 0 && (
            <>
              <h3 className="chi-section-title">Pending Leases</h3>
              <div className="chi-lease-list">
                {pendingLeases.map(l => (
                  <div key={l.id} className={`chi-lease-card${selectedLease?.id === l.id ? ' selected' : ''}`}
                    onClick={() => setSelectedLease(l)}>
                    <div className="chi-lease-header">
                      <span className="chi-lease-name">{l.name}</span>
                      <span className={`chi-status ${statusClass(l.status)}`}>{l.status}</span>
                    </div>
                    <div className="chi-lease-meta">
                      <span>{l._site}</span>
                      <span>{formatDate(l.start_date)} → {formatDate(l.end_date)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          {pastLeases.length > 0 && (
            <>
              <h3 className="chi-section-title">Past Leases ({pastLeases.length})</h3>
              <div className="chi-lease-list">
                {pastLeases.slice(0, 20).map(l => (
                  <div key={l.id} className={`chi-lease-card past${selectedLease?.id === l.id ? ' selected' : ''}`}
                    onClick={() => setSelectedLease(l)}>
                    <div className="chi-lease-header">
                      <span className="chi-lease-name">{l.name}</span>
                      <span className={`chi-status ${statusClass(l.status)}`}>{l.status}</span>
                    </div>
                    <div className="chi-lease-meta">
                      <span>{l._site}</span>
                      <span>{formatDate(l.start_date)} → {formatDate(l.end_date)}</span>
                    </div>
                  </div>
                ))}
                {pastLeases.length > 20 && (
                  <div className="chi-more">...and {pastLeases.length - 20} more</div>
                )}
              </div>
            </>
          )}

          {/* Archive terminal leases */}
          {leases.filter(l => l.status === 'TERMINATED' || l.status === 'ERROR').length > 0 && (
            <button
              className="chi-action-btn"
              style={{ marginTop: 8 }}
              onClick={() => {
                const terminal = leases.filter(l => l.status === 'TERMINATED' || l.status === 'ERROR');
                setConfirmAction({ title: 'Clear Terminal Leases', message: `Archive ${terminal.length} terminated/error lease(s)?`, onConfirm: async () => {
                  for (const l of terminal) {
                    try { await api.deleteChameleonLease(l.id, l._site); } catch { /* continue */ }
                  }
                  refresh();
                }});
              }}
            >
              Clear {leases.filter(l => l.status === 'TERMINATED' || l.status === 'ERROR').length} Terminal
            </button>
          )}

          {leases.length === 0 && !loading && (
            <div className="chi-empty">No leases found. Create one using the CLI: <code>loomai chameleon leases create</code></div>
          )}
        </div>
      )}

      {/* Map tab — Chameleon sites + instance overlay */}
      {tab === 'map' && (
        <GeoView
          sliceData={null}
          selectedElement={null}
          onNodeClick={() => {}}
          sites={[]}
          links={[]}
          linksLoading={false}
          siteMetricsCache={{}}
          linkMetricsCache={{}}
          metricsRefreshRate={0}
          onMetricsRefreshRateChange={() => {}}
          onRefreshMetrics={() => {}}
          metricsLoading={false}
          chameleonSites={sites.filter(s => s.configured)}
          chameleonInstances={instances}
          defaultShowInfra={false}
        />
      )}

      {/* Table tab rendered by ChameleonTableView */}
      {tab === 'slices' && (
        <ChameleonTableView
          instances={instances}
          onInstanceAction={handleInstanceAction}
          onRefresh={refresh}
          loading={loading}
        />
      )}

      {/* Resources tab removed — functionality available in OpenStack tab + editor */}
      {false && tab === 'resources' && (
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
          <div className="chi-resource-category-bar">
            <button className={`chi-resource-category-btn${resourceCat === 'sites' ? ' active' : ''}`} onClick={() => setResourceCat('sites')}>Sites</button>
            <button className={`chi-resource-category-btn${resourceCat === 'node-types' ? ' active' : ''}`} onClick={() => setResourceCat('node-types')}>Node Types</button>
            <button className={`chi-resource-category-btn${resourceCat === 'networks' ? ' active' : ''}`} onClick={() => setResourceCat('networks')}>Networks</button>
          </div>
          <div style={{ flex: 1, overflow: 'auto' }}>
            {resourceCat === 'sites' && (
              <div className="chi-content">
                <h3 className="chi-section-title">Chameleon Sites</h3>
                <div className="chi-site-list">
                  {sites.map(s => (
                    <div key={s.name} className="chi-site-card">
                      <div className="chi-site-header">
                        <span className="chi-site-name">{s.name}</span>
                        <span className={`chi-site-status ${s.configured ? 'configured' : 'not-configured'}`}>
                          {s.configured ? 'Configured' : 'Not Configured'}
                        </span>
                      </div>
                      <div className="chi-site-meta">
                        {s.location.city && <span>{s.location.city}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {resourceCat === 'node-types' && (
              <div className="chi-content">
                <h3 className="chi-section-title">Node Types by Site</h3>
                {sites.filter(s => s.configured).map(s => {
                  const siteTypes = detailedNodeTypes[s.name] || [];
                  return (
                    <div key={s.name} style={{ marginBottom: 16 }}>
                      <h4 style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>{s.name}</h4>
                      <div className="chi-browse-grid">
                        {siteTypes.length > 0 ? (
                          siteTypes.map(nt => (
                            <div key={nt.node_type} className="chi-browse-card">
                              <div className="chi-browse-type">{nt.node_type}</div>
                              <div className="chi-browse-count">{nt.reservable}/{nt.total} available</div>
                              {nt.cpu_model && <div className="chi-browse-spec">CPU: {nt.cpu_model}{nt.cpu_count ? ` x${nt.cpu_count}` : ''}</div>}
                              {!nt.cpu_model && nt.cpu_arch && <div className="chi-browse-spec">Arch: {nt.cpu_arch}{nt.cpu_count ? ` x${nt.cpu_count}` : ''}</div>}
                              {nt.ram_gb != null && <div className="chi-browse-spec">RAM: {nt.ram_gb} GB</div>}
                              {nt.disk_gb != null && <div className="chi-browse-spec">Disk: {nt.disk_gb} GB</div>}
                              {nt.gpu && (
                                <div className="chi-browse-gpu">
                                  GPU: {nt.gpu}{nt.gpu_count && nt.gpu_count > 1 ? ` x${nt.gpu_count}` : ''}
                                </div>
                              )}
                            </div>
                          ))
                        ) : (
                          <div style={{ fontSize: 12, color: 'var(--fabric-text-muted)' }}>Loading node types...</div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            {resourceCat === 'networks' && (
              <div className="chi-content">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <h3 className="chi-section-title" style={{ margin: 0 }}>Networks</h3>
                  <button className="chi-create-btn" onClick={() => {
                    setShowCreateNetwork(true);
                    if (!newNetSite && sites.filter(s => s.configured).length > 0) {
                      setNewNetSite(sites.filter(s => s.configured)[0].name);
                    }
                  }}>+ Network</button>
                </div>

                {showCreateNetwork && (
                  <div className="chi-network-card" style={{ marginBottom: 12, background: 'var(--fabric-bg-secondary, #f9f9f9)' }}>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                      <div style={{ flex: 1, minWidth: 120 }}>
                        <label className="chi-form-label" style={{ margin: '0 0 2px 0' }}>Site</label>
                        <select className="chi-form-input" value={newNetSite} onChange={e => setNewNetSite(e.target.value)}>
                          {sites.filter(s => s.configured).map(s => (
                            <option key={s.name} value={s.name}>{s.name}</option>
                          ))}
                        </select>
                      </div>
                      <div style={{ flex: 1, minWidth: 120 }}>
                        <label className="chi-form-label" style={{ margin: '0 0 2px 0' }}>Name</label>
                        <input className="chi-form-input" type="text" value={newNetName} onChange={e => setNewNetName(e.target.value)} placeholder="my-network" />
                      </div>
                      <div style={{ flex: 1, minWidth: 120 }}>
                        <label className="chi-form-label" style={{ margin: '0 0 2px 0' }}>CIDR</label>
                        <input className="chi-form-input" type="text" value={newNetCidr} onChange={e => setNewNetCidr(e.target.value)} placeholder="192.168.1.0/24" />
                      </div>
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button className="success" style={{ padding: '5px 12px', fontSize: 11 }} onClick={handleCreateNetwork} disabled={createNetLoading || !newNetName.trim()}>
                          {createNetLoading ? 'Creating...' : 'Create'}
                        </button>
                        <button style={{ padding: '5px 10px', fontSize: 11 }} onClick={() => setShowCreateNetwork(false)}>Cancel</button>
                      </div>
                    </div>
                  </div>
                )}

                {networks.length > 0 ? (
                  <div className="chi-lease-list">
                    {networks.map(net => (
                      <div key={net.id} className="chi-network-card">
                        <div className="chi-lease-header">
                          <span className="chi-lease-name">{net.name}</span>
                          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                            {net.status && <span className={`chi-status ${statusClass(net.status)}`}>{net.status}</span>}
                            {net.shared && <span style={{ fontSize: 10, color: 'var(--fabric-text-muted)' }}>shared</span>}
                          </div>
                        </div>
                        <div className="chi-lease-meta">
                          <span>{net.site}</span>
                          {net.subnet_details && net.subnet_details.length > 0 && (
                            <span>{net.subnet_details.map(s => s.cidr).join(', ')}</span>
                          )}
                        </div>
                        {!net.shared && (
                          <div className="chi-instance-actions">
                            <button
                              className="chi-action-btn chi-action-btn-danger"
                              onClick={(e) => { e.stopPropagation(); handleDeleteNetwork(net.id, net.site); }}
                              title="Delete network"
                            >
                              Delete
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="chi-empty">No networks found.</div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === 'calendar' && (
        <ChameleonCalendar
          sites={sites}
          onCreateLease={(startDate) => {
            if (startDate) {
              setStartNow(false);
              setCreateStartDate(startDate);
            } else {
              setStartNow(true);
              setCreateStartDate('');
            }
            setShowCreateLease(true);
          }}
        />
      )}

      {/* Selected lease detail panel */}
      {selectedLease && (
        <div className="chi-detail-panel">
          <div className="chi-detail-header">
            <h3>{selectedLease.name}</h3>
            <button className="chi-detail-close" onClick={() => setSelectedLease(null)}>{'\u2715'}</button>
          </div>
          <table className="chi-detail-table">
            <tbody>
              <tr><td>ID</td><td><code>{selectedLease.id}</code></td></tr>
              <tr><td>Site</td><td>{selectedLease._site}</td></tr>
              <tr><td>Status</td><td><span className={`chi-status ${statusClass(selectedLease.status)}`}>{selectedLease.status}</span></td></tr>
              <tr><td>Start</td><td>{formatDate(selectedLease.start_date)}</td></tr>
              <tr><td>End</td><td>{formatDate(selectedLease.end_date)}</td></tr>
              {selectedLease.reservations.length > 0 && (
                <tr><td>Reservations</td><td>
                  {selectedLease.reservations.map(r => (
                    <div key={r.id} style={{ marginBottom: 4 }}>
                      <strong>{r.resource_type || 'unknown'}</strong>
                      <span style={{ marginLeft: 6 }}>{r.min}-{r.max} nodes</span>
                      {r.status && <span className={`chi-status ${statusClass(r.status)}`} style={{ marginLeft: 6 }}>{r.status}</span>}
                      <div style={{ fontSize: 10, color: 'var(--fabric-text-muted)' }}>ID: {r.id}</div>
                    </div>
                  ))}
                </td></tr>
              )}
            </tbody>
          </table>

          {/* Extend Lease */}
          {selectedLease.status === 'ACTIVE' && (
            <div className="chi-extend-row">
              <span style={{ fontSize: 12, fontWeight: 600 }}>Extend:</span>
              <input
                type="number" min={1} max={168}
                value={extendHours}
                onChange={e => setExtendHours(Number(e.target.value))}
                className="chi-form-input"
                style={{ width: 60 }}
              />
              <span style={{ fontSize: 11, color: 'var(--fabric-text-muted)' }}>hrs</span>
              <button
                className="chi-action-btn"
                onClick={handleExtendLease}
                disabled={extendLoading}
              >
                {extendLoading ? 'Extending...' : 'Extend'}
              </button>
            </div>
          )}

          {/* Delete Lease */}
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--fabric-border)' }}>
            <button
              className="chi-action-btn chi-action-btn-danger"
              onClick={handleDeleteLease}
              disabled={deleteLeaseLoading}
            >
              {deleteLeaseLoading ? 'Deleting...' : 'Delete Lease'}
            </button>
          </div>
        </div>
      )}

      {/* Create Lease Modal — portal to body, inline styles for guaranteed centering */}
      {showCreateLease && typeof document !== 'undefined' && createPortal(
        <div className="toolbar-modal-overlay" style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.5)', zIndex: 99999 }} onClick={() => setShowCreateLease(false)}>
          <div className="toolbar-modal toolbar-modal-wide" onClick={e => e.stopPropagation()} style={{ maxHeight: '80vh', overflowY: 'auto' }}>
            <h4>Create Chameleon Lease</h4>
            {createError && <div className="chi-error" style={{ marginBottom: 8 }}>{createError}</div>}

            <label className="toolbar-modal-label">Site</label>
            <select className="toolbar-modal-input" value={createSite} onChange={e => { setCreateSite(e.target.value); setCreateNodeType(''); setAvailResult(null); }}>
              {sites.filter(s => s.configured).map(s => (
                <option key={s.name} value={s.name}>{s.name}</option>
              ))}
            </select>

            <label className="toolbar-modal-label">Lease Name</label>
            <input className="toolbar-modal-input" type="text" value={createName} onChange={e => setCreateName(e.target.value)} placeholder="my-experiment" />

            <label className="toolbar-modal-label">Resource Type</label>
            <select className="toolbar-modal-input" value={resourceType} onChange={e => setResourceType(e.target.value)}>
              <option value="physical:host">Compute / GPU (bare-metal)</option>
              <option value="network">Network (isolated VLAN)</option>
              <option value="virtual:floatingip">Floating IPs</option>
            </select>

            {resourceType === 'physical:host' && (
              <>
                <label className="toolbar-modal-label">Node Type {nodeTypesLoading && '(loading...)'}</label>
                <select className="toolbar-modal-input" value={createNodeType} onChange={e => { setCreateNodeType(e.target.value); setAvailResult(null); }} disabled={nodeTypesLoading}>
                  {nodeTypes.length === 0 && <option value="">-- select --</option>}
                  {nodeTypes.map(nt => {
                    const detail = getDetailForNodeType(nt.node_type);
                    let label = `${nt.node_type} (${nt.reservable}/${nt.total} available)`;
                    if (detail) {
                      const parts: string[] = [];
                      if (detail.cpu_count) parts.push(`${detail.cpu_count}c`);
                      if (detail.ram_gb) parts.push(`${detail.ram_gb}GB`);
                      if (detail.disk_gb) parts.push(`${detail.disk_gb}GB disk`);
                      if (parts.length > 0) {
                        label = `${nt.node_type} \u2014 ${parts.join(', ')} (${nt.reservable}/${nt.total} avail)`;
                      }
                    }
                    return (
                      <option key={nt.node_type} value={nt.node_type}>
                        {label}
                      </option>
                    );
                  })}
                </select>
              </>
            )}

            {resourceType === 'network' && (
              <>
                <label className="toolbar-modal-label">Network Name</label>
                <input className="toolbar-modal-input" type="text" value={networkName} onChange={e => setNetworkName(e.target.value)} placeholder="my-network" />
              </>
            )}

            <div style={{ display: 'flex', gap: 8 }}>
              <div style={{ flex: 1 }}>
                <label className="toolbar-modal-label">{resourceType === 'virtual:floatingip' ? 'IP Count' : 'Node Count'}</label>
                <input className="toolbar-modal-input" type="number" min={1} max={20} value={createCount} onChange={e => setCreateCount(Number(e.target.value))} />
              </div>
              <div style={{ flex: 1 }}>
                <label className="toolbar-modal-label">Duration (hours)</label>
                <input className="toolbar-modal-input" type="number" min={1} max={168} value={createHours} onChange={e => setCreateHours(Number(e.target.value))} />
              </div>
            </div>

            {/* Start time */}
            <div style={{ marginTop: 8 }}>
              <label className="toolbar-modal-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={startNow} onChange={e => setStartNow(e.target.checked)} />
                Start now
              </label>
              {!startNow && (
                <input className="toolbar-modal-input" type="datetime-local" value={createStartDate}
                  onChange={e => setCreateStartDate(e.target.value)} style={{ marginTop: 4 }} />
              )}
            </div>

            {/* Availability finder */}
            {resourceType === 'physical:host' && createNodeType && (
              <div style={{ marginTop: 8, padding: 8, background: 'var(--fabric-bg-tint, #f5f5f5)', borderRadius: 6 }}>
                <button
                  onClick={handleFindAvailability}
                  disabled={availLoading}
                  style={{ fontSize: 11, padding: '3px 10px' }}
                >
                  {availLoading ? 'Checking...' : 'Find Earliest Availability'}
                </button>
                {availResult && (
                  <div style={{ fontSize: 11, marginTop: 4 }}>
                    {availResult.error ? (
                      <span style={{ color: 'var(--fabric-coral, #e25241)' }}>{availResult.error}</span>
                    ) : availResult.earliest_start === 'now' ? (
                      <span style={{ color: 'var(--fabric-success, #008e7a)' }}>Available now ({availResult.available_now}/{availResult.total} free)</span>
                    ) : availResult.earliest_start ? (
                      <span>Earliest: <strong>{availResult.earliest_start}</strong> ({availResult.available_now}/{availResult.total} free now)</span>
                    ) : (
                      <span style={{ color: 'var(--fabric-text-muted)' }}>No availability found</span>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="toolbar-modal-actions" style={{ marginTop: 16 }}>
              <button onClick={() => setShowCreateLease(false)}>Cancel</button>
              <button className="success" onClick={handleCreateLease} disabled={createSubmitting || !createName.trim() || (resourceType === 'physical:host' && !createNodeType)}>
                {createSubmitting ? 'Creating...' : 'Create Lease'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {/* Confirmation modal — shared by all confirm actions */}
      {confirmAction && typeof document !== 'undefined' && createPortal(
        <div className="toolbar-modal-overlay" style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.5)', zIndex: 99999 }} onClick={() => setConfirmAction(null)}>
          <div className="toolbar-modal" onClick={e => e.stopPropagation()}>
            <h4>{confirmAction.title}</h4>
            <p>{confirmAction.message}</p>
            <div className="toolbar-modal-actions">
              <button onClick={() => setConfirmAction(null)}>Cancel</button>
              <button className={confirmAction.danger ? 'danger' : 'primary'} onClick={() => { confirmAction.onConfirm(); setConfirmAction(null); }}>
                {confirmAction.danger ? 'Delete' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  );

  if (hideBar) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        {content}
      </div>
    );
  }

  return (
    <TestbedViewShell
      theme={CHAMELEON_THEME}
      tabs={tabs}
      activeTab={tab}
      onTabChange={(id) => setTab(id as typeof tab)}
      toolbarContent={toolbarContent}
    >
      {content}
    </TestbedViewShell>
  );
}
