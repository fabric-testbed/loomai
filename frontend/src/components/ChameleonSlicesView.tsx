'use client';
import React, { useState, useMemo } from 'react';
import type { ChameleonDraft } from '../types/chameleon';
import '../styles/chameleon-slices-view.css';

interface ChameleonSlicesViewProps {
  drafts: ChameleonDraft[];
  leases: Array<{ id: string; name: string; _site: string; status: string; start_date: string; end_date: string; reservations?: any[] }>;
  instances: Array<{ id: string; name: string; site: string; status: string; ip_addresses: string[]; floating_ip?: string; image: string }>;
  selectedDraftId?: string;
  selectedInstanceId?: string;
  onDraftSelect?: (draftId: string) => void;
  onDeleteDrafts?: (draftIds: string[]) => void;
  onOpenTerminal?: (instance: { id: string; name: string; site: string }) => void;
  onInstanceSelect?: (instanceId: string, site: string) => void;
  onRefresh?: () => void;
  loading?: boolean;
}

function statusClass(status: string): string {
  const s = (status || '').toUpperCase();
  if (s === 'ACTIVE' || s === 'STABLEOK') return 'chi-status-active';
  if (s === 'PENDING' || s === 'DRAFT' || s === 'CONFIGURING' || s === 'BUILD') return 'chi-status-pending';
  if (s === 'ERROR') return 'chi-status-error';
  return 'chi-status-terminated';
}

type SortCol = 'name' | 'site' | 'status' | 'nodes';
type ParentRow = { type: 'draft'; draft: ChameleonDraft } | { type: 'lease'; lease: any };

export default React.memo(function ChameleonSlicesView({
  drafts, leases, instances, selectedDraftId, selectedInstanceId, onDraftSelect, onDeleteDrafts, onOpenTerminal, onInstanceSelect, onRefresh, loading,
}: ChameleonSlicesViewProps) {
  const [filterText, setFilterText] = useState('');
  const [sortCol, setSortCol] = useState<SortCol>('name');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);

  // Build parent rows
  const allRows: ParentRow[] = useMemo(() => {
    const rows: ParentRow[] = [];
    for (const d of drafts) rows.push({ type: 'draft', draft: d });
    for (const l of leases) rows.push({ type: 'lease', lease: l });
    return rows;
  }, [drafts, leases]);

  // Filter
  const filtered = useMemo(() => {
    if (!filterText) return allRows;
    const q = filterText.toLowerCase();
    return allRows.filter(r => {
      if (r.type === 'draft') return r.draft.name.toLowerCase().includes(q) || (r.draft.site || '').toLowerCase().includes(q) || r.draft.nodes.some(n => n.site?.toLowerCase().includes(q)) || 'draft'.includes(q);
      return r.lease.name.toLowerCase().includes(q) || r.lease._site?.toLowerCase().includes(q) || r.lease.status?.toLowerCase().includes(q);
    });
  }, [allRows, filterText]);

  // Sort
  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      const aName = a.type === 'draft' ? a.draft.name : a.lease.name;
      const bName = b.type === 'draft' ? b.draft.name : b.lease.name;
      const aSite = a.type === 'draft' ? (a.draft.site || [...new Set(a.draft.nodes.map(n => n.site))].join(', ')) : a.lease._site || '';
      const bSite = b.type === 'draft' ? (b.draft.site || [...new Set(b.draft.nodes.map(n => n.site))].join(', ')) : b.lease._site || '';
      const aStatus = a.type === 'draft' ? 'Draft' : a.lease.status;
      const bStatus = b.type === 'draft' ? 'Draft' : b.lease.status;
      const aNodes = a.type === 'draft' ? a.draft.nodes.length : (a.lease.reservations?.length || 0);
      const bNodes = b.type === 'draft' ? b.draft.nodes.length : (b.lease.reservations?.length || 0);

      let cmp = 0;
      if (sortCol === 'name') cmp = aName.localeCompare(bName);
      else if (sortCol === 'site') cmp = aSite.localeCompare(bSite);
      else if (sortCol === 'status') cmp = aStatus.localeCompare(bStatus);
      else if (sortCol === 'nodes') cmp = aNodes - bNodes;
      return sortDir === 'asc' ? cmp : -cmp;
    });
    // Always put drafts first
    arr.sort((a, b) => (a.type === 'draft' ? -1 : 0) - (b.type === 'draft' ? -1 : 0));
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
  const allDraftIds = useMemo(() => sorted.filter(r => r.type === 'draft').map(r => (r as any).draft.id as string), [sorted]);
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
    if (!window.confirm(`Delete ${ids.length} selected slice${ids.length !== 1 ? 's' : ''}?`)) return;
    setBulkDeleting(true);
    onDeleteDrafts?.(ids);
    setCheckedIds(new Set());
    setBulkDeleting(false);
  };

  // Match instances to leases by site (best-effort)
  const instancesBySite = useMemo(() => {
    const map: Record<string, typeof instances> = {};
    for (const inst of instances) {
      (map[inst.site] ??= []).push(inst);
    }
    return map;
  }, [instances]);

  return (
    <div className="chi-sv-view">
      {/* Action bar */}
      <div className="chi-sv-action-bar">
        <input className="chi-sv-filter" placeholder="Filter by name, site, status..." value={filterText} onChange={e => setFilterText(e.target.value)} />
        <span className="chi-sv-count">{filtered.length} of {allRows.length} items</span>
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
              <th onClick={() => handleSort('nodes')} style={{ cursor: 'pointer' }}>Nodes{sortArrow('nodes')}</th>
              <th>Networks</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(row => {
              const id = row.type === 'draft' ? `draft:${row.draft.id}` : `lease:${row.lease.id}`;
              const name = row.type === 'draft' ? row.draft.name : row.lease.name;
              const site = row.type === 'draft' ? (row.draft.site || [...new Set(row.draft.nodes.map(n => n.site))].join(', ')) : row.lease._site || '';
              const status = row.type === 'draft' ? 'Draft' : row.lease.status;
              const nodeCount = row.type === 'draft' ? row.draft.nodes.length : (row.lease.reservations?.length || 0);
              const netCount = row.type === 'draft' ? row.draft.networks.length : 0;
              const isExpanded = expanded.has(id);
              const isSelected = row.type === 'draft' && selectedDraftId === row.draft.id;

              return (
                <React.Fragment key={id}>
                  {/* Parent row */}
                  <tr className={`chi-sv-parent ${isSelected ? 'chi-sv-active' : ''}${row.type === 'draft' && checkedIds.has(row.draft.id) ? ' chi-sv-checked' : ''}`}>
                    <td style={{ width: 28 }} onClick={e => e.stopPropagation()}>
                      {row.type === 'draft' && <input type="checkbox" checked={checkedIds.has(row.draft.id)} onChange={() => toggleCheck(row.draft.id)} />}
                    </td>
                    <td className="chi-sv-expand-cell" onClick={() => toggleExpand(id)}>
                      <span className="chi-sv-expand-btn">{isExpanded ? '▼' : '▶'}</span>
                    </td>
                    <td className="chi-sv-name" onClick={() => row.type === 'draft' && onDraftSelect?.(row.draft.id)}>
                      {name}
                      {row.type === 'draft' && <span className="chi-sv-type-badge">Draft</span>}
                      {row.type === 'lease' && <span className="chi-sv-type-badge chi-sv-type-lease">Lease</span>}
                    </td>
                    <td>{site}</td>
                    <td><span className={`chi-status ${statusClass(status)}`}>{status}</span></td>
                    <td>{nodeCount}</td>
                    <td>{netCount || '—'}</td>
                  </tr>

                  {/* Child rows */}
                  {isExpanded && row.type === 'draft' && (
                    <>
                      {row.draft.nodes.map(n => (
                        <tr key={`${id}:node:${n.id}`} className="chi-sv-child">
                          <td></td><td></td>
                          <td style={{ paddingLeft: 24 }}>{n.name}</td>
                          <td>{n.site || row.draft.site || ''}</td>
                          <td><span className="chi-status chi-status-pending">Draft</span></td>
                          <td style={{ fontSize: 10 }}>{n.node_type}</td>
                          <td style={{ fontSize: 10 }}>{n.image}</td>
                        </tr>
                      ))}
                      {row.draft.networks.map(n => (
                        <tr key={`${id}:net:${n.id}`} className="chi-sv-child chi-sv-network">
                          <td></td><td></td>
                          <td style={{ paddingLeft: 24 }}>🔗 {n.name}</td>
                          <td></td>
                          <td><span className="chi-status chi-status-pending">Network</span></td>
                          <td colSpan={2} style={{ fontSize: 10 }}>{n.connected_nodes?.length || 0} connected</td>
                        </tr>
                      ))}
                      {row.draft.nodes.length === 0 && row.draft.networks.length === 0 && (
                        <tr className="chi-sv-child"><td></td><td></td><td colSpan={5} style={{ color: 'var(--fabric-text-muted)', fontStyle: 'italic' }}>Empty draft — add nodes in the Editor</td></tr>
                      )}
                    </>
                  )}

                  {isExpanded && row.type === 'lease' && (
                    <>
                      {(row.lease.reservations || []).map((r: any, i: number) => (
                        <tr key={`${id}:res:${i}`} className="chi-sv-child">
                          <td></td><td></td>
                          <td style={{ paddingLeft: 24 }}>Reservation {i + 1}</td>
                          <td>{r.resource_type || 'physical:host'}</td>
                          <td><span className={`chi-status ${statusClass(r.status || status)}`}>{r.status || status}</span></td>
                          <td>{r.min || r.max || '—'} nodes</td>
                          <td></td>
                        </tr>
                      ))}
                      {(instancesBySite[site] || []).map(inst => {
                        const hasIp = inst.floating_ip || (inst.ip_addresses && inst.ip_addresses.length > 0);
                        return (
                          <tr key={`${id}:inst:${inst.id}`}
                            className={`chi-sv-child${selectedInstanceId === inst.id ? ' chi-sv-active' : ''}`}
                            style={{ cursor: 'pointer' }}
                            onClick={() => onInstanceSelect?.(inst.id, inst.site)}>
                            <td></td><td></td>
                            <td style={{ paddingLeft: 24 }}>⚙ {inst.name}</td>
                            <td>{inst.site}</td>
                            <td><span className={`chi-status ${statusClass(inst.status)}`}>{inst.status}</span></td>
                            <td style={{ fontSize: 10 }}>
                              {inst.floating_ip && <span style={{ color: 'var(--fabric-teal, #008e7a)', fontWeight: 600, fontFamily: 'monospace' }}>{inst.floating_ip}</span>}
                              {!inst.floating_ip && inst.ip_addresses?.[0] && <span style={{ fontFamily: 'monospace' }}>{inst.ip_addresses[0]}</span>}
                              {!inst.floating_ip && !inst.ip_addresses?.[0] && '—'}
                            </td>
                            <td style={{ fontSize: 10 }}>
                              {inst.status === 'ACTIVE' && hasIp && onOpenTerminal && (
                                <button style={{ fontSize: 10, padding: '1px 5px', marginRight: 3, cursor: 'pointer', background: 'none', border: '1px solid #39B54A', borderRadius: 3, color: '#39B54A' }}
                                  onClick={(e) => { e.stopPropagation(); onOpenTerminal({ id: inst.id, name: inst.name, site: inst.site }); }}>
                                  SSH
                                </button>
                              )}
                              {inst.image}
                            </td>
                          </tr>
                        );
                      })}
                      {(row.lease.reservations || []).length === 0 && !instancesBySite[site]?.length && (
                        <tr className="chi-sv-child"><td></td><td></td><td colSpan={5} style={{ color: 'var(--fabric-text-muted)', fontStyle: 'italic' }}>No reservations or instances</td></tr>
                      )}
                    </>
                  )}
                </React.Fragment>
              );
            })}
            {sorted.length === 0 && (
              <tr><td colSpan={7} style={{ textAlign: 'center', padding: 24, color: 'var(--fabric-text-muted)' }}>
                {allRows.length === 0 ? 'No drafts or leases. Create a draft with "+ New".' : 'No matches for filter.'}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
});
