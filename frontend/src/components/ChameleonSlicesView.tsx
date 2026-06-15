'use client';
import React, { useState, useMemo } from 'react';
import { createPortal } from 'react-dom';
import * as api from '../api/client';
import type { ChameleonDraft, ChameleonLease } from '../types/chameleon';
import { alertDialog, confirmDialog } from './AppDialogProvider';
import '../styles/chameleon-slices-view.css';

type ChameleonLeaseRow = ChameleonLease & { site?: string };

interface ChameleonSlicesViewProps {
  drafts: ChameleonDraft[];
  instances: Array<{ id: string; name: string; site: string; status: string; ip_addresses: string[]; floating_ip?: string; image: string }>;
  leases?: ChameleonLeaseRow[];
  selectedDraftId?: string;
  selectedInstanceId?: string;
  onDraftSelect?: (draftId: string) => void;
  onDraftUpdated?: (draft: ChameleonDraft) => void;
  onDeleteDrafts?: (draftIds: string[]) => void;
  onOpenTerminal?: (instance: { id: string; name: string; site: string }) => void;
  onInstanceSelect?: (instanceId: string, site: string) => void;
  onRefresh?: () => void | Promise<void>;
  loading?: boolean;
  federatedSliceLinks?: Record<string, { id: string; name: string; state?: string }>;
  onFederatedSliceOpen?: (id: string) => void;
}

function statusClass(status: string): string {
  const s = (status || '').toUpperCase();
  if (s === 'ACTIVE' || s === 'STABLEOK') return 'chi-status-active';
  if (s === 'PENDING' || s === 'DRAFT' || s === 'CONFIGURING' || s === 'BUILD') return 'chi-status-pending';
  if (s === 'ERROR') return 'chi-status-error';
  return 'chi-status-terminated';
}

type SortCol = 'name' | 'site' | 'status' | 'nodes';
type LeaseCandidateSortCol = 'membership' | 'name' | 'site' | 'status' | 'start' | 'end' | 'reservations' | 'id';

interface LeaseCandidate {
  lease: ChameleonLeaseRow;
  id: string;
  key: string;
  name: string;
  site: string;
  status: string;
  start: string;
  end: string;
  reservations: string;
  membership: 'attached' | 'available';
  searchable: string;
}

function isLegacyLeaseRecord(value: ChameleonDraft): boolean {
  const row = value as any;
  return Array.isArray(row.reservations) && Boolean(row.start_date || row.end_date || row._site);
}

const RESOURCE_LABELS: Record<string, string> = {
  instance: 'Server',
  lease: 'Reservation',
  network: 'Network',
  floating_ip: 'Floating IP',
  security_group: 'Security Group',
};

function resourceLabel(resource: ChameleonDraft['resources'][number]): string {
  return resource.type_label || RESOURCE_LABELS[resource.type] || resource.type.replace(/_/g, ' ');
}

function shortId(value?: string): string {
  if (!value) return '';
  return value.length > 14 ? `${value.slice(0, 12)}...` : value;
}

function leaseResourceKey(resource: { id?: string; site?: string; _site?: string }): string {
  return `${resource.site || resource._site || ''}:${resource.id || ''}`;
}

function formatLeaseDate(value?: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function leaseReservationSummary(lease: ChameleonLeaseRow): string {
  const reservations = lease.reservations || [];
  if (reservations.length === 0) return '-';
  return reservations.map((reservation) => {
    const capacity = reservation.min || reservation.max
      ? ` ${reservation.min ?? ''}-${reservation.max ?? ''}`.trim()
      : '';
    return `${reservation.resource_type || 'reservation'}${capacity ? ` ${capacity}` : ''}`;
  }).join(', ');
}

function instanceResourceMatchesNode(
  resource: ChameleonDraft['resources'][number],
  node: ChameleonDraft['nodes'][number],
): boolean {
  if (resource.type !== 'instance') return false;
  const relationship = resource.relationship || {};
  const plannedNodeId = resource.planned_node_id || relationship.planned_node_id || '';
  const plannedNodeName = resource.planned_node_name || relationship.planned_node_name || '';
  const sameSite = !resource.site || !node.site || resource.site === node.site;
  return Boolean(
    (plannedNodeId && plannedNodeId === node.id)
    || (sameSite && plannedNodeName && plannedNodeName === node.name)
    || (sameSite && resource.name && resource.name === node.name),
  );
}

function plannedNodeDeployStatus(
  slice: ChameleonDraft,
  node: ChameleonDraft['nodes'][number],
  instanceResource?: ChameleonDraft['resources'][number],
): string {
  if (instanceResource?.status) return instanceResource.status;
  if ((slice.state || '').toLowerCase() !== 'deploying') return node.status || 'Draft';
  const site = node.site || slice.site || '';
  const lease = (slice.resources || []).find(resource => resource.type === 'lease' && (!site || resource.site === site));
  if (!lease) return 'Waiting for lease';
  const leaseStatus = (lease.status || '').toUpperCase();
  if (leaseStatus === 'ACTIVE') return 'Waiting for launch';
  if (leaseStatus === 'ERROR') return 'Blocked by lease error';
  return `Waiting for lease ${lease.status || 'PENDING'}`;
}

export default React.memo(function ChameleonSlicesView({
  drafts, instances, leases = [], selectedDraftId, selectedInstanceId, onDraftSelect, onDraftUpdated, onDeleteDrafts, onOpenTerminal, onInstanceSelect, onRefresh, loading, federatedSliceLinks, onFederatedSliceOpen,
}: ChameleonSlicesViewProps) {
  const [filterText, setFilterText] = useState('');
  const [sortCol, setSortCol] = useState<SortCol>('name');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [leaseMembershipBusy, setLeaseMembershipBusy] = useState<Set<string>>(new Set());
  const [leaseDialogSliceId, setLeaseDialogSliceId] = useState<string | null>(null);
  const [leaseCandidateFilter, setLeaseCandidateFilter] = useState('');
  const [leaseCandidateSort, setLeaseCandidateSort] = useState<{ key: LeaseCandidateSortCol; dir: 'asc' | 'desc' }>({
    key: 'name',
    dir: 'asc',
  });

  const allRows = useMemo(() => drafts.filter(slice => !isLegacyLeaseRecord(slice)), [drafts]);
  const leaseDialogSlice = useMemo(
    () => allRows.find(slice => slice.id === leaseDialogSliceId) || null,
    [allRows, leaseDialogSliceId],
  );

  const leaseOwnershipByKey = useMemo(() => {
    const owners = new Map<string, string>();
    for (const slice of allRows) {
      for (const resource of slice.resources || []) {
        if (resource.type !== 'lease' || !resource.id) continue;
        owners.set(leaseResourceKey(resource), slice.id);
      }
    }
    return owners;
  }, [allRows]);

  const getSliceSites = (slice: ChameleonDraft): string => {
    const sites = [
      ...(slice.sites || []),
      ...(slice.site ? [slice.site] : []),
      ...((slice.nodes || []).map(n => n.site).filter(Boolean) as string[]),
      ...((slice.resources || []).map(r => r.site).filter(Boolean) as string[]),
    ];
    return [...new Set(sites)].join(', ');
  };

  const getSliceNodeCount = (slice: ChameleonDraft): number => {
    const planned = (slice.nodes || []).reduce((sum, node) => {
      const count = Number(node.count ?? 1);
      return sum + (Number.isFinite(count) ? Math.max(1, Math.floor(count)) : 1);
    }, 0);
    const deployed = (slice.resources || []).filter(r => r.type === 'instance').length;
    return Math.max(planned, deployed);
  };

  const getSliceReservationCount = (slice: ChameleonDraft): number => {
    return (slice.resources || []).filter(r => r.type === 'lease').length;
  };

  // Filter
  const filtered = useMemo(() => {
    if (!filterText) return allRows;
    const q = filterText.toLowerCase();
    return allRows.filter(slice => {
      const resourceText = (slice.resources || [])
        .map(r => `${r.name || ''} ${r.type || ''} ${r.status || ''} ${r.site || ''} ${r.ownership || ''}`)
        .join(' ')
        .toLowerCase();
      return slice.name.toLowerCase().includes(q)
        || (slice.state || '').toLowerCase().includes(q)
        || getSliceSites(slice).toLowerCase().includes(q)
        || (slice.nodes || []).some(n => `${n.name} ${n.site || ''} ${n.node_type || ''}`.toLowerCase().includes(q))
        || resourceText.includes(q);
    });
  }, [allRows, filterText]);

  // Sort
  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      const aName = a.name;
      const bName = b.name;
      const aSite = getSliceSites(a);
      const bSite = getSliceSites(b);
      const aStatus = a.state || 'Draft';
      const bStatus = b.state || 'Draft';
      const aNodes = getSliceNodeCount(a);
      const bNodes = getSliceNodeCount(b);

      let cmp = 0;
      if (sortCol === 'name') cmp = aName.localeCompare(bName);
      else if (sortCol === 'site') cmp = aSite.localeCompare(bSite);
      else if (sortCol === 'status') cmp = aStatus.localeCompare(bStatus);
      else if (sortCol === 'nodes') cmp = aNodes - bNodes;
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return arr;
  }, [filtered, sortCol, sortDir]);

  const toggleExpand = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleSort = (col: SortCol) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('asc'); }
  };

  const sortArrow = (col: SortCol) => sortCol === col ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '';

  // Checkbox helpers
  const allDraftIds = useMemo(() => sorted.map(slice => slice.id), [sorted]);
  const toggleCheck = (id: string) => setCheckedIds(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const toggleCheckAll = () => setCheckedIds(prev => {
    if (allDraftIds.every(id => prev.has(id))) return new Set();
    return new Set(allDraftIds);
  });
  const handleBulkDelete = async () => {
    const ids = Array.from(checkedIds);
    if (ids.length === 0) return;
    if (!await confirmDialog(`Delete ${ids.length} selected slice${ids.length !== 1 ? 's' : ''}?`, {
      title: 'Delete Chameleon Slices',
      confirmLabel: 'Delete',
      tone: 'danger',
    })) return;
    setBulkDeleting(true);
    onDeleteDrafts?.(ids);
    setCheckedIds(new Set());
    setBulkDeleting(false);
  };

  const instancesById = useMemo(() => {
    const map: Record<string, typeof instances[number]> = {};
    for (const inst of instances) {
      map[inst.id] = inst;
    }
    return map;
  }, [instances]);

  const handleLeaseMembershipChange = async (
    slice: ChameleonDraft,
    lease: ChameleonLeaseRow,
    include: boolean,
  ) => {
    const site = lease.site || lease._site || '';
    const busyKey = `${slice.id}:${site}:${lease.id}`;
    setLeaseMembershipBusy(prev => new Set(prev).add(busyKey));
    try {
      let updated: ChameleonDraft | undefined;
      if (include) {
        await api.importChameleonReservation(slice.id, site, lease.id, { include_lease: true });
        updated = await api.getChameleonDraft(slice.id);
      } else {
        const resource = (slice.resources || []).find(r => (
          r.type === 'lease'
          && r.id === lease.id
          && (!site || !r.site || r.site === site)
        ));
        if (resource) {
          updated = await api.removeChameleonSliceResource(slice.id, resource.resource_id);
        }
      }
      if (updated) onDraftUpdated?.(updated);
      await onRefresh?.();
    } catch (e: any) {
      await alertDialog(e?.message || 'Failed to update Chameleon lease membership', {
        title: 'Lease Update Failed',
      });
    } finally {
      setLeaseMembershipBusy(prev => {
        const next = new Set(prev);
        next.delete(busyKey);
        return next;
      });
    }
  };

  const handleLeaseCandidateSort = (key: LeaseCandidateSortCol) => {
    setLeaseCandidateSort(prev => (
      prev.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'asc' }
    ));
  };

  const openLeaseDialog = (slice: ChameleonDraft) => {
    setLeaseDialogSliceId(slice.id);
    setLeaseCandidateFilter('');
    setLeaseCandidateSort({ key: 'name', dir: 'asc' });
  };

  const leaseDialogAttachedKeys = useMemo(() => new Set(
    (leaseDialogSlice?.resources || [])
      .filter(resource => resource.type === 'lease')
      .map(resource => leaseResourceKey(resource)),
  ), [leaseDialogSlice]);

  const leaseCandidates = useMemo<LeaseCandidate[]>(() => {
    if (!leaseDialogSlice) return [];
    const leaseRowsByKey = new Map<string, ChameleonLeaseRow>();
    for (const lease of leases) {
      if (!lease.id) continue;
      leaseRowsByKey.set(leaseResourceKey(lease), lease);
    }
    for (const resource of leaseDialogSlice.resources || []) {
      if (resource.type !== 'lease' || !resource.id) continue;
      const key = leaseResourceKey(resource);
      if (leaseRowsByKey.has(key)) continue;
      leaseRowsByKey.set(key, {
        id: resource.id,
        name: resource.name || resource.id,
        _site: resource.site || '',
        site: resource.site || '',
        status: resource.status || 'UNKNOWN',
        start_date: resource.start_date || '',
        end_date: resource.end_date || '',
        project_id: undefined,
        reservations: resource.reservations || [],
      });
    }

    const candidates = Array.from(leaseRowsByKey.values())
      .filter(lease => Boolean(lease.id))
      .filter(lease => {
        const key = leaseResourceKey(lease);
        const owner = leaseOwnershipByKey.get(key);
        return !owner || owner === leaseDialogSlice.id;
      })
      .map(lease => {
        const id = lease.id || '';
        const site = lease.site || lease._site || '';
        const key = leaseResourceKey(lease);
        const name = lease.name || id;
        const status = lease.status || 'UNKNOWN';
        const start = lease.start_date || '';
        const end = lease.end_date || '';
        const reservations = leaseReservationSummary(lease);
        const membership: LeaseCandidate['membership'] = leaseDialogAttachedKeys.has(key) ? 'attached' : 'available';
        const searchable = [
          membership === 'attached' ? 'attached remove included' : 'available add',
          name,
          id,
          site,
          status,
          start,
          end,
          reservations,
        ].join(' ').toLowerCase();
        return { lease, id, key, name, site, status, start, end, reservations, membership, searchable };
      });

    const filter = leaseCandidateFilter.trim().toLowerCase();
    const filteredCandidates = candidates.filter(candidate => !filter || candidate.searchable.includes(filter));
    const direction = leaseCandidateSort.dir === 'asc' ? 1 : -1;
    return filteredCandidates.sort((a, b) => {
      const key = leaseCandidateSort.key;
      let cmp = 0;
      if (key === 'reservations') {
        cmp = (a.lease.reservations?.length || 0) - (b.lease.reservations?.length || 0);
      } else {
        cmp = String(a[key] ?? '').toLowerCase().localeCompare(String(b[key] ?? '').toLowerCase());
      }
      return cmp === 0 ? a.name.localeCompare(b.name) : cmp * direction;
    });
  }, [leaseCandidateFilter, leaseCandidateSort, leaseDialogAttachedKeys, leaseDialogSlice, leaseOwnershipByKey, leases]);

  const leaseCandidateSortArrow = (key: LeaseCandidateSortCol) => (
    leaseCandidateSort.key === key ? (leaseCandidateSort.dir === 'asc' ? ' ▲' : ' ▼') : ''
  );

  return (
    <div className="chi-sv-view">
      {/* Action bar */}
      <div className="chi-sv-action-bar">
        <input className="chi-sv-filter" placeholder="Filter by name, site, status..." value={filterText} onChange={e => setFilterText(e.target.value)} />
        <span className="chi-sv-count">{filtered.length} of {allRows.length} slices</span>
        <button className="chi-sv-refresh" onClick={onRefresh} disabled={loading}>{loading ? '...' : '↻'}</button>
      </div>

      {/* Bulk action bar */}
      {checkedIds.size > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 12px', background: 'var(--fabric-bg-tint)', borderBottom: '1px solid var(--fabric-border)', fontSize: 12, color: 'var(--fabric-text)' }}>
          <span style={{ fontWeight: 600 }}>{checkedIds.size} selected</span>
          <button className="chi-sv-refresh" style={{ color: 'var(--fabric-coral, #e25241)', border: '1px solid var(--fabric-coral, #e25241)' }} onClick={handleBulkDelete} disabled={bulkDeleting}>
            {bulkDeleting ? 'Deleting...' : `Delete ${checkedIds.size}`}
          </button>
          <button className="chi-sv-refresh" onClick={() => setCheckedIds(new Set())} style={{ marginLeft: 'auto' }}>Clear</button>
        </div>
      )}

      {/* Table */}
      <div className="chi-sv-table-wrapper">
        <table className="chi-sv-table">
          <thead>
            <tr>
              <th style={{ width: 28 }}>
                <input type="checkbox" checked={allDraftIds.length > 0 && allDraftIds.every(id => checkedIds.has(id))} onChange={toggleCheckAll} title="Select all" />
              </th>
              <th style={{ width: 28 }}></th>
              <th onClick={() => handleSort('name')} style={{ cursor: 'pointer' }}>Name{sortArrow('name')}</th>
              <th onClick={() => handleSort('site')} style={{ cursor: 'pointer' }}>Site{sortArrow('site')}</th>
              <th onClick={() => handleSort('status')} style={{ cursor: 'pointer' }}>Status{sortArrow('status')}</th>
              <th onClick={() => handleSort('nodes')} style={{ cursor: 'pointer' }}>Servers{sortArrow('nodes')}</th>
              <th>Reservations</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(slice => {
              const id = `slice:${slice.id}`;
              const site = getSliceSites(slice);
              const status = slice.state || 'Draft';
              const nodeCount = getSliceNodeCount(slice);
              const reservationCount = getSliceReservationCount(slice);
              const nodes = slice.nodes || [];
              const networks = slice.networks || [];
              const isExpanded = expanded.has(id);
              const isSelected = selectedDraftId === slice.id;
              const federatedLink = federatedSliceLinks?.[slice.id] || federatedSliceLinks?.[slice.name];
              const nodeResourceMatches = new Map<string, ChameleonDraft['resources'][number]>();
              const matchedResourceKeys = new Set<string>();
              for (const node of nodes) {
                const match = (slice.resources || []).find(resource => instanceResourceMatchesNode(resource, node));
                if (match) {
                  nodeResourceMatches.set(node.id, match);
                  matchedResourceKeys.add(match.resource_id || match.id);
                }
              }
              const resourceRows = (slice.resources || []).filter(resource => (
                resource.type !== 'instance' || !matchedResourceKeys.has(resource.resource_id || resource.id)
              ));
              const attachedLeaseKeys = new Set(
                (slice.resources || [])
                  .filter(resource => resource.type === 'lease')
                  .map(resource => leaseResourceKey(resource)),
              );

              return (
                <React.Fragment key={id}>
                  {/* Parent row */}
                  <tr
                    className={`chi-sv-parent ${isSelected ? 'chi-sv-active' : ''}${checkedIds.has(slice.id) ? ' chi-sv-checked' : ''}`}
                    data-testid="chameleon-slice-row"
                    data-slice-id={slice.id}
                    data-slice-name={slice.name}
                  >
                    <td style={{ width: 28 }} onClick={e => e.stopPropagation()}>
                      <input type="checkbox" checked={checkedIds.has(slice.id)} onChange={() => toggleCheck(slice.id)} />
                    </td>
                    <td className="chi-sv-expand-cell" onClick={() => toggleExpand(id)}>
                      <button
                        type="button"
                        className={`chi-sv-expand-btn${isExpanded ? ' expanded' : ''}`}
                        onClick={(e) => { e.stopPropagation(); toggleExpand(id); }}
                        title={isExpanded ? 'Collapse' : 'Expand'}
                        aria-label={isExpanded ? `Collapse ${slice.name}` : `Expand ${slice.name}`}
                      >
                        {isExpanded ? '\u25BE' : '\u25B8'}
                      </button>
                    </td>
                    <td className="chi-sv-name" onClick={() => onDraftSelect?.(slice.id)}>
                      {slice.name}
                      <span className={`chi-sv-type-badge${status === 'Draft' ? '' : ' chi-sv-type-lease'}`}>{status === 'Draft' ? 'Draft' : 'Slice'}</span>
                      {federatedLink && (
                        <button
                          type="button"
                          className="chi-sv-federated-link-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            onFederatedSliceOpen?.(federatedLink.id);
                          }}
                          title={`Open federated slice ${federatedLink.name}`}
                        >
                          Federated: {federatedLink.name}
                        </button>
                      )}
                    </td>
                    <td>{site}</td>
                    <td><span className={`chi-status ${statusClass(status)}`}>{status}</span></td>
                    <td>{nodeCount}</td>
                    <td>{reservationCount || '—'}</td>
                  </tr>

                  {/* Expanded resource detail */}
                  {isExpanded && (
                    <tr className="chi-sv-detail-row">
                      <td colSpan={7}>
                        <div className="chi-sv-detail">
                          <div className="chi-sv-lease-membership">
                            <div className="chi-sv-lease-membership-header">
                              <div>
                                <span className="chi-sv-lease-membership-title">Lease Membership</span>
                                <span className="chi-sv-lease-membership-subtitle">
                                  {attachedLeaseKeys.size} attached Chameleon lease{attachedLeaseKeys.size === 1 ? '' : 's'}.
                                </span>
                              </div>
                              <div className="chi-sv-lease-membership-actions">
                                <button className="chi-sv-refresh" onClick={onRefresh} disabled={loading}>
                                  {loading ? '...' : 'Refresh Leases'}
                                </button>
                                <button
                                  className="chi-sv-primary-action"
                                  onClick={() => openLeaseDialog(slice)}
                                  data-testid="chameleon-add-lease"
                                >
                                  + Add Chameleon Lease
                                </button>
                              </div>
                            </div>
                            {attachedLeaseKeys.size === 0 ? (
                              <div className="chi-sv-lease-empty">No Chameleon leases are attached to this slice.</div>
                            ) : (
                              <div className="chi-sv-attached-lease-list">
                                {(slice.resources || []).filter(resource => resource.type === 'lease').map(resource => (
                                  <span key={resource.resource_id || resource.id} className="chi-sv-attached-lease-pill">
                                    <span>{resource.name || resource.id}</span>
                                    <span className={`chi-status ${statusClass(resource.status || 'UNKNOWN')}`}>{resource.status || 'UNKNOWN'}</span>
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                          <table className="chi-sv-resource-table">
                            <thead>
                              <tr>
                                <th style={{ width: 92 }}>Type</th>
                                <th>Name</th>
                                <th>Site</th>
                                <th>Status</th>
                                <th>Address/Detail</th>
                                <th>Image/Role</th>
                              </tr>
                            </thead>
                            <tbody>
                              {nodes.map(n => {
                                const match = nodeResourceMatches.get(n.id);
                                const live = match ? instancesById[match.id] : undefined;
                                const nodeStatus = live?.status || plannedNodeDeployStatus(slice, n, match);
                                const resourceSite = live?.site || match?.site || n.site || slice.site || '';
                                const floatingIp = live?.floating_ip || match?.floating_ip || n.floating_ip || '';
                                const ipAddresses = live?.ip_addresses || match?.ip_addresses || n.ip_addresses || [];
                                const displayAddress = floatingIp || n.management_ip || ipAddresses[0] || '';
                                const statusKey = nodeStatus.toUpperCase();
                                const instanceId = match?.id || n.instance_id || '';
                                const canSsh = statusKey === 'ACTIVE' && Boolean(instanceId && floatingIp && onOpenTerminal);
                                return (
                                  <tr
                                    key={`${id}:node:${n.id}`}
                                    className={instanceId && selectedInstanceId === instanceId ? 'chi-sv-active' : ''}
                                    style={{ cursor: instanceId ? 'pointer' : 'default' }}
                                    onClick={() => instanceId && onInstanceSelect?.(instanceId, resourceSite)}
                                  >
                                    <td><span className="chi-sv-resource-kind chi-sv-kind-server">Server</span></td>
                                    <td className="chi-sv-resource-name">{n.name}</td>
                                    <td>{resourceSite || <span className="chi-sv-muted">-</span>}</td>
                                    <td><span className={`chi-status ${statusClass(nodeStatus)}`}>{nodeStatus}</span></td>
                                    <td>
                                      {canSsh && (
                                        <button
                                          className="chi-sv-ssh-btn"
                                          onClick={(e) => { e.stopPropagation(); onOpenTerminal?.({ id: instanceId, name: n.name, site: resourceSite }); }}
                                        >
                                          SSH
                                        </button>
                                      )}
                                      <span className={displayAddress ? 'chi-sv-mono-strong' : ''}>
                                        {displayAddress || `${n.node_type}${Number(n.count ?? 1) > 1 ? ` x${n.count}` : ''}`}
                                      </span>
                                    </td>
                                    <td>{n.image || <span className="chi-sv-muted">-</span>}</td>
                                  </tr>
                                );
                              })}
                              {networks.map(n => (
                                <tr key={`${id}:net:${n.id}`}>
                                  <td><span className="chi-sv-resource-kind chi-sv-kind-network">Network</span></td>
                                  <td className="chi-sv-resource-name">{n.name}</td>
                                  <td></td>
                                  <td><span className="chi-status chi-status-pending">Network</span></td>
                                  <td>{n.connected_nodes?.length || 0} connected</td>
                                  <td></td>
                                </tr>
                              ))}
                              {resourceRows.map(resource => {
                                const live = resource.type === 'instance' ? instancesById[resource.id] : undefined;
                                const resourceStatus = live?.status || resource.status || '';
                                const statusKey = (resourceStatus || resource.type).toUpperCase();
                                const resourceSite = live?.site || resource.site || '';
                                const floatingIp = live?.floating_ip || resource.floating_ip;
                                const ipAddresses = live?.ip_addresses || resource.ip_addresses || [];
                                const canSsh = resource.type === 'instance' && statusKey === 'ACTIVE' && Boolean(floatingIp && onOpenTerminal);
                                const label = resourceLabel(resource);
                                const resourceName = resource.name || floatingIp || resource.id;
                                const primaryDetail = resource.type === 'instance'
                                  ? (floatingIp || ipAddresses[0] || '-')
                                  : resource.type === 'lease'
                                    ? `${shortId(resource.lease_id || resource.id)}${resource.reservations?.length ? ` (${resource.reservations.length} reservation${resource.reservations.length === 1 ? '' : 's'})` : ''}`
                                    : resource.type === 'floating_ip'
                                      ? (floatingIp || resource.name || shortId(resource.id))
                                      : resource.type === 'network'
                                        ? (resource.cidr || shortId(resource.id) || '-')
                                        : shortId(resource.id) || resource.type;
                                return (
                                  <React.Fragment key={`${id}:resource:${resource.resource_id || resource.id}`}>
                                    <tr
                                      className={resource.type === 'instance' && selectedInstanceId === resource.id ? 'chi-sv-active' : ''}
                                      style={{ cursor: resource.type === 'instance' ? 'pointer' : 'default' }}
                                      onClick={() => resource.type === 'instance' && onInstanceSelect?.(resource.id, resourceSite)}
                                    >
                                      <td><span className={`chi-sv-resource-kind${resource.type === 'instance' ? ' chi-sv-kind-server' : resource.type === 'network' ? ' chi-sv-kind-network' : ' chi-sv-kind-resource'}`}>{label}</span></td>
                                      <td className="chi-sv-resource-name">
                                        {resourceName}
                                        {resource.ownership === 'imported' && <span className="chi-sv-type-badge chi-sv-type-lease">Imported</span>}
                                      </td>
                                      <td>{resourceSite || <span className="chi-sv-muted">-</span>}</td>
                                      <td><span className={`chi-status ${statusClass(resourceStatus || resource.type)}`}>{resourceStatus || label}</span></td>
                                      <td>
                                        {canSsh && (
                                          <button
                                            className="chi-sv-ssh-btn"
                                            onClick={(e) => { e.stopPropagation(); onOpenTerminal?.({ id: resource.id, name: resource.name || resource.id, site: resourceSite }); }}
                                          >
                                            SSH
                                          </button>
                                        )}
                                        <span className={resource.type === 'instance' || resource.type === 'floating_ip' ? 'chi-sv-mono-strong' : 'chi-sv-mono'}>{primaryDetail}</span>
                                      </td>
                                      <td>{resource.type === 'instance' ? (live?.image || resource.image || '') : label}</td>
                                    </tr>
                                    {resource.type === 'lease' && (resource.reservations || []).map((reservation: any, idx: number) => (
                                      <tr key={`${id}:resource:${resource.resource_id || resource.id}:reservation:${reservation.id || idx}`}>
                                        <td><span className="chi-sv-resource-kind chi-sv-kind-reservation">Reservation</span></td>
                                        <td className="chi-sv-resource-name">{reservation.id ? shortId(reservation.id) : `reservation-${idx + 1}`}</td>
                                        <td>{resourceSite || <span className="chi-sv-muted">-</span>}</td>
                                        <td><span className={`chi-status ${statusClass(reservation.status || resourceStatus || 'PENDING')}`}>{reservation.status || resourceStatus || 'PENDING'}</span></td>
                                        <td>{reservation.resource_type || resource.resource_type || 'physical:host'}</td>
                                        <td>{reservation.min || reservation.max ? `${reservation.min ?? ''}-${reservation.max ?? ''}` : 'Reserved capacity'}</td>
                                      </tr>
                                    ))}
                                  </React.Fragment>
                                );
                              })}
                              {nodes.length === 0 && networks.length === 0 && resourceRows.length === 0 && (
                                <tr>
                                  <td colSpan={6} className="chi-sv-detail-empty">No Chameleon resources in this slice.</td>
                                </tr>
                              )}
                            </tbody>
                          </table>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
            {sorted.length === 0 && (
              <tr><td colSpan={7} style={{ textAlign: 'center', padding: 24, color: 'var(--fabric-text-muted)' }}>
                {allRows.length === 0 ? 'No Chameleon slices. Create one with "+ New".' : 'No matches for filter.'}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      {leaseDialogSlice && typeof document !== 'undefined' && createPortal(
        <div
          className="chi-sv-modal-overlay"
          onClick={() => setLeaseDialogSliceId(null)}
          data-testid="chameleon-lease-modal-overlay"
        >
          <div
            className="chi-sv-lease-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="chameleon-lease-modal-title"
            data-testid="chameleon-lease-modal"
          >
            <h4 id="chameleon-lease-modal-title">Add Chameleon Lease</h4>
            <p>
              Attach or remove existing Chameleon leases for <strong>{leaseDialogSlice.name}</strong>.
            </p>
            <div className="chi-sv-lease-modal-controls">
              <div className="chi-sv-lease-modal-filter">
                <label htmlFor="chi-lease-candidate-filter">Filter candidates</label>
                <input
                  id="chi-lease-candidate-filter"
                  className="chi-sv-filter"
                  aria-label="Filter candidate Chameleon leases"
                  placeholder="Filter by name, state, site, reservation, date, or ID..."
                  value={leaseCandidateFilter}
                  onChange={(e) => setLeaseCandidateFilter(e.target.value)}
                  autoFocus
                />
              </div>
              <button className="chi-sv-refresh" onClick={onRefresh} disabled={loading}>
                {loading ? '...' : 'Refresh Leases'}
              </button>
              <span>
                {leaseCandidates.length} candidate{leaseCandidates.length === 1 ? '' : 's'}
              </span>
            </div>
            <div className="chi-sv-candidate-table-wrap">
              <table className="chi-sv-candidate-table">
                <thead>
                  <tr>
                    {([
                      ['membership', 'Membership'],
                      ['name', 'Name'],
                      ['site', 'Site'],
                      ['status', 'State'],
                      ['start', 'Start'],
                      ['end', 'End'],
                      ['reservations', 'Reservations'],
                      ['id', 'ID'],
                    ] as Array<[LeaseCandidateSortCol, string]>).map(([key, label]) => (
                      <th key={key}>
                        <button
                          type="button"
                          onClick={() => handleLeaseCandidateSort(key)}
                          title={`Sort by ${label}`}
                        >
                          {label}{leaseCandidateSortArrow(key)}
                        </button>
                      </th>
                    ))}
                    <th className="chi-sv-candidate-action-column"></th>
                  </tr>
                </thead>
                <tbody>
                  {leaseCandidates.map(candidate => {
                    const busyKey = `${leaseDialogSlice.id}:${candidate.site}:${candidate.id}`;
                    const busy = leaseMembershipBusy.has(busyKey);
                    const attached = candidate.membership === 'attached';
                    return (
                      <tr
                        key={candidate.key}
                        data-testid="chameleon-lease-candidate"
                        data-lease-id={candidate.id}
                        data-lease-name={candidate.name}
                        data-site={candidate.site}
                        data-membership={candidate.membership}
                      >
                        <td>
                          <span className={`chi-sv-lease-membership-badge ${attached ? 'attached' : 'available'}`}>
                            {attached ? 'Attached' : 'Available'}
                          </span>
                        </td>
                        <td className="chi-sv-candidate-name">{candidate.name}</td>
                        <td>{candidate.site || '-'}</td>
                        <td><span className={`chi-status ${statusClass(candidate.status)}`}>{candidate.status}</span></td>
                        <td className="chi-sv-candidate-muted">{formatLeaseDate(candidate.start) || '-'}</td>
                        <td className="chi-sv-candidate-muted">{formatLeaseDate(candidate.end) || '-'}</td>
                        <td>{candidate.reservations}</td>
                        <td className="chi-sv-candidate-id" title={candidate.id}>{candidate.id}</td>
                        <td className="chi-sv-candidate-actions">
                          <button
                            className={attached ? 'danger' : 'primary'}
                            disabled={busy}
                            data-testid="chameleon-lease-toggle"
                            onClick={() => handleLeaseMembershipChange(leaseDialogSlice, candidate.lease, !attached)}
                          >
                            {busy ? '...' : attached ? 'Remove' : 'Add'}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {leaseCandidates.length === 0 && (
                    <tr>
                      <td colSpan={9} className="chi-sv-candidate-empty">
                        No candidate Chameleon leases match the current filter.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="chi-sv-modal-actions">
              <button onClick={() => setLeaseDialogSliceId(null)} data-testid="chameleon-lease-modal-close">Close</button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
});
