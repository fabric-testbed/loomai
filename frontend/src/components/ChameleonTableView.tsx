'use client';
import React, { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import type { ChameleonInstance } from '../types/chameleon';
import '../styles/chameleon-table-view.css';
import '../styles/context-menu.css';

interface ChameleonTableViewProps {
  instances: ChameleonInstance[];
  onInstanceAction: (instanceId: string, site: string, action: 'reboot' | 'stop' | 'start' | 'delete' | 'ssh') => void;
  onRefresh: () => void;
  loading: boolean;
}

function statusClass(status: string): string {
  const s = status.toLowerCase();
  if (s === 'active') return 'chi-status-active';
  if (s === 'build' || s === 'pending') return 'chi-status-pending';
  if (s === 'error') return 'chi-status-error';
  return 'chi-status-terminated';
}

function formatDate(d: string | undefined): string {
  if (!d) return '';
  return d.replace('T', ' ').slice(0, 16);
}

type SortCol = 'name' | 'site' | 'status' | 'ip' | 'image' | 'created';

interface MenuState {
  x: number;
  y: number;
  instance: ChameleonInstance;
}

export default React.memo(function ChameleonTableView({
  instances,
  onInstanceAction,
  onRefresh,
  loading,
}: ChameleonTableViewProps) {
  const [filterText, setFilterText] = useState('');
  const [sortCol, setSortCol] = useState<SortCol>('name');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set());
  const [menu, setMenu] = useState<MenuState | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Dismiss context menu on click outside
  useEffect(() => {
    if (!menu) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenu(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [menu]);

  const getIp = useCallback((inst: ChameleonInstance): string => {
    if (inst.floating_ip) return inst.floating_ip;
    if (inst.ip_addresses.length > 0) return inst.ip_addresses.join(', ');
    return '';
  }, []);

  // Filter
  const filtered = useMemo(() => {
    if (!filterText.trim()) return instances;
    const lower = filterText.toLowerCase();
    return instances.filter(inst =>
      inst.name.toLowerCase().includes(lower) ||
      inst.site.toLowerCase().includes(lower) ||
      inst.status.toLowerCase().includes(lower) ||
      getIp(inst).toLowerCase().includes(lower)
    );
  }, [instances, filterText, getIp]);

  // Sort
  const sorted = useMemo(() => {
    const arr = [...filtered];
    const dir = sortDir === 'asc' ? 1 : -1;
    arr.sort((a, b) => {
      let va = '', vb = '';
      switch (sortCol) {
        case 'name': va = a.name; vb = b.name; break;
        case 'site': va = a.site; vb = b.site; break;
        case 'status': va = a.status; vb = b.status; break;
        case 'ip': va = getIp(a); vb = getIp(b); break;
        case 'image': va = a.image; vb = b.image; break;
        case 'created': va = a.created || ''; vb = b.created || ''; break;
      }
      return va.localeCompare(vb) * dir;
    });
    return arr;
  }, [filtered, sortCol, sortDir, getIp]);

  const handleSort = useCallback((col: SortCol) => {
    setSortCol(prev => {
      if (prev === col) {
        setSortDir(d => d === 'asc' ? 'desc' : 'asc');
        return col;
      }
      setSortDir('asc');
      return col;
    });
  }, []);

  const toggleSelect = useCallback((id: string) => {
    setSelectedItems(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelectedItems(prev => {
      if (prev.size === sorted.length && sorted.length > 0) return new Set();
      return new Set(sorted.map(i => i.id));
    });
  }, [sorted]);

  const handleBulkDelete = useCallback(() => {
    if (selectedItems.size === 0) return;
    if (!window.confirm(`Delete ${selectedItems.size} instance(s)?`)) return;
    for (const id of selectedItems) {
      const inst = instances.find(i => i.id === id);
      if (inst) onInstanceAction(id, inst.site, 'delete');
    }
    setSelectedItems(new Set());
  }, [selectedItems, instances, onInstanceAction]);

  const handleContextMenu = useCallback((e: React.MouseEvent, inst: ChameleonInstance) => {
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY, instance: inst });
  }, []);

  const handleMenuAction = useCallback((action: 'ssh' | 'reboot' | 'stop' | 'start' | 'delete') => {
    if (!menu) return;
    onInstanceAction(menu.instance.id, menu.instance.site, action);
    setMenu(null);
  }, [menu, onInstanceAction]);

  const arrow = (col: SortCol) => sortCol === col ? (sortDir === 'asc' ? ' \u25B2' : ' \u25BC') : '';

  const hasIp = (inst: ChameleonInstance) => !!(inst.floating_ip || inst.ip_addresses.length > 0);

  return (
    <div className="chi-table-view">
      {/* Action bar */}
      <div className="chi-table-action-bar">
        <input
          type="text"
          placeholder="Filter instances..."
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
        />
        <span className="chi-table-count">{sorted.length} instance{sorted.length !== 1 ? 's' : ''}</span>
        {selectedItems.size > 0 && (
          <button
            className="chi-ssh-btn"
            style={{ borderColor: '#b00020', color: '#b00020' }}
            onClick={handleBulkDelete}
          >
            Delete ({selectedItems.size})
          </button>
        )}
        <button
          className="chi-refresh"
          onClick={onRefresh}
          disabled={loading}
          title="Refresh instances"
        >
          {loading ? '\u23F3' : '\u21BB'}
        </button>
      </div>

      {/* Table */}
      <div className="chi-table-wrapper">
        <table className="chi-table">
          <thead>
            <tr>
              <th style={{ width: 30 }}>
                <input
                  type="checkbox"
                  checked={sorted.length > 0 && selectedItems.size === sorted.length}
                  onChange={toggleSelectAll}
                />
              </th>
              <th onClick={() => handleSort('name')}>Name{arrow('name')}</th>
              <th onClick={() => handleSort('site')}>Site{arrow('site')}</th>
              <th onClick={() => handleSort('status')}>Status{arrow('status')}</th>
              <th onClick={() => handleSort('ip')}>IP{arrow('ip')}</th>
              <th onClick={() => handleSort('image')}>Image{arrow('image')}</th>
              <th onClick={() => handleSort('created')}>Created{arrow('created')}</th>
              <th style={{ width: 80 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(inst => (
              <tr
                key={inst.id}
                className={selectedItems.has(inst.id) ? 'selected' : ''}
                onContextMenu={(e) => handleContextMenu(e, inst)}
              >
                <td>
                  <input
                    type="checkbox"
                    checked={selectedItems.has(inst.id)}
                    onChange={() => toggleSelect(inst.id)}
                  />
                </td>
                <td title={inst.name}>{inst.name}</td>
                <td>{inst.site}</td>
                <td>
                  <span className={`chi-status ${statusClass(inst.status)}`}>
                    {inst.status}
                  </span>
                </td>
                <td title={getIp(inst)}>{getIp(inst) || '\u2014'}</td>
                <td className="chi-table-image" title={inst.image}>{inst.image}</td>
                <td>{formatDate(inst.created)}</td>
                <td>
                  {inst.status === 'ACTIVE' && hasIp(inst) && (
                    <button
                      className="chi-ssh-btn"
                      onClick={() => onInstanceAction(inst.id, inst.site, 'ssh')}
                      title={`SSH to ${inst.name}`}
                      style={{ marginRight: 4 }}
                    >
                      SSH
                    </button>
                  )}
                  <button
                    className="chi-refresh"
                    style={{ fontSize: 11, padding: '2px 6px' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      const rect = (e.target as HTMLElement).getBoundingClientRect();
                      setMenu({ x: rect.left, y: rect.bottom, instance: inst });
                    }}
                    title="More actions"
                  >
                    ...
                  </button>
                </td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: 24, color: 'var(--fabric-text-muted)' }}>
                  {instances.length === 0 ? 'No instances running.' : 'No instances match filter.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Context menu */}
      {menu && (
        <div
          ref={menuRef}
          className="graph-context-menu"
          style={{ left: menu.x, top: menu.y }}
        >
          <div className="graph-context-menu-label">{menu.instance.name}</div>
          {menu.instance.status === 'ACTIVE' && hasIp(menu.instance) && (
            <button className="graph-context-menu-item" onClick={() => handleMenuAction('ssh')}>
              SSH
            </button>
          )}
          {menu.instance.status === 'ACTIVE' && (
            <button className="graph-context-menu-item" onClick={() => handleMenuAction('reboot')}>
              Reboot
            </button>
          )}
          {menu.instance.status === 'ACTIVE' && (
            <button className="graph-context-menu-item" onClick={() => handleMenuAction('stop')}>
              Stop
            </button>
          )}
          {menu.instance.status === 'SHUTOFF' && (
            <button className="graph-context-menu-item" onClick={() => handleMenuAction('start')}>
              Start
            </button>
          )}
          <div className="graph-context-menu-sep" />
          <button className="graph-context-menu-item danger" onClick={() => handleMenuAction('delete')}>
            Delete
          </button>
        </div>
      )}
    </div>
  );
});
