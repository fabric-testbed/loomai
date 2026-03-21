'use client';
import React, { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import type { SliceSummary, SliceData, SliceNode, SliceNetwork, RecipeSummary } from '../types/fabric';
import type { ContextMenuAction } from './CytoscapeGraph';
import * as api from '../api/client';
import Tooltip from './Tooltip';
import '../styles/sliver-view.css';
import '../styles/context-menu.css';

interface AllSliversViewProps {
  slices: SliceSummary[];
  dark: boolean;
  onSliceSelect: (id: string) => void;
  onDeleteSlice: (name: string) => Promise<void>;
  onRefreshSlices: () => void;
  onContextAction?: (action: ContextMenuAction) => void;
  nodeActivity?: Record<string, string>;
  recipes?: RecipeSummary[];
}

// --- Helpers ---

function stateClass(state: string): string {
  const s = state.toLowerCase();
  if (s === 'stableok') return 'stable-ok';
  if (s === 'stableerror') return 'stable-error';
  if (s === 'modifyok') return 'stable-ok';
  if (s === 'modifyerror') return 'stable-error';
  if (s.includes('active')) return 'active';
  if (s.includes('configuring')) return 'configuring';
  if (s.includes('nascent')) return 'nascent';
  if (s.includes('closing')) return 'closing';
  if (s.includes('dead')) return 'dead';
  if (s.includes('ticketed')) return 'ticketed';
  if (s.includes('allocat')) return 'allocating';
  if (s.includes('draft')) return 'nascent';
  return '';
}

function formatLeaseEnd(lease: string): string {
  if (!lease) return '';
  try {
    const d = new Date(lease);
    if (isNaN(d.getTime())) return lease;
    const now = new Date();
    const diffMs = d.getTime() - now.getTime();
    const diffH = Math.round(diffMs / 3600000);
    const dateStr = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const timeStr = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    if (diffH < 0) return `${dateStr} ${timeStr} (expired)`;
    if (diffH < 24) return `${dateStr} ${timeStr} (${diffH}h)`;
    const diffD = Math.round(diffH / 24);
    return `${dateStr} ${timeStr} (${diffD}d)`;
  } catch {
    return lease;
  }
}

// --- Context menu state ---

interface MenuState {
  x: number;
  y: number;
  rows: Record<string, string>[];
  sliceNames?: string[];
}

// --- Main component ---

export default React.memo(function AllSliversView({
  slices,
  dark,
  onSliceSelect,
  onDeleteSlice,
  onRefreshSlices,
  onContextAction,
  nodeActivity,
  recipes,
}: AllSliversViewProps) {
  // Expanded slices
  const [expandedSlices, setExpandedSlices] = useState<Set<string>>(new Set());
  // Lazy-fetched slice data cache
  const [sliceCache, setSliceCache] = useState<Map<string, SliceData>>(new Map());
  // Currently loading slices
  const [loadingSlices, setLoadingSlices] = useState<Set<string>>(new Set());
  // Multi-select: composite keys like "slice:name", "node:sliceName/nodeName", "net:sliceName/netName"
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set());
  // Filter
  const [filterText, setFilterText] = useState('');
  // Sort state for slice rows
  const [sliceSort, setSliceSort] = useState<'name' | 'state' | 'lease_end' | 'nodes' | 'networks'>('name');
  const [sliceSortDir, setSliceSortDir] = useState<'asc' | 'desc'>('asc');
  // Sort state for sliver (child) rows — applies to all expanded slices uniformly
  const [sliverSort, setSliverSort] = useState<'name' | 'site' | 'host' | 'state' | 'resources' | 'ip'>('name');
  const [sliverSortDir, setSliverSortDir] = useState<'asc' | 'desc'>('asc');
  // Context menu
  const [menu, setMenu] = useState<MenuState | null>(null);
  // Busy deleting
  const [deleting, setDeleting] = useState(false);

  // Close context menu on click-away or Escape
  useEffect(() => {
    if (!menu) return;
    const handleClick = () => setMenu(null);
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(null); };
    document.addEventListener('click', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('click', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [menu]);

  // Toggle expand/collapse for a slice
  const toggleExpand = useCallback(async (name: string) => {
    setExpandedSlices(prev => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
    // Fetch if not cached
    if (!sliceCache.has(name) && !loadingSlices.has(name)) {
      setLoadingSlices(prev => { const n = new Set(prev); n.add(name); return n; });
      try {
        const data = await api.getSlice(name);
        setSliceCache(prev => { const n = new Map(prev); n.set(name, data); return n; });
      } catch {
        // silently fail — row will show "Failed to load"
      } finally {
        setLoadingSlices(prev => { const n = new Set(prev); n.delete(name); return n; });
      }
    }
  }, [sliceCache, loadingSlices]);

  // Refresh a single slice's cache
  const refreshSliceCache = useCallback(async (name: string) => {
    setLoadingSlices(prev => { const n = new Set(prev); n.add(name); return n; });
    try {
      const data = await api.getSlice(name);
      setSliceCache(prev => { const n = new Map(prev); n.set(name, data); return n; });
    } catch {
      // ignore
    } finally {
      setLoadingSlices(prev => { const n = new Set(prev); n.delete(name); return n; });
    }
  }, []);

  // Auto-refresh expanded slices when their state changes (detected via slices prop)
  const prevSliceStatesRef = useRef<Record<string, string>>({});
  useEffect(() => {
    for (const s of slices) {
      const prev = prevSliceStatesRef.current[s.name];
      if (prev && prev !== s.state && expandedSlices.has(s.name) && sliceCache.has(s.name)) {
        refreshSliceCache(s.name);
      }
      prevSliceStatesRef.current[s.name] = s.state;
    }
  }, [slices, expandedSlices, sliceCache, refreshSliceCache]);

  // --- Selection helpers ---

  const sliceKey = (name: string) => `slice:${name}`;
  const nodeKey = (sliceName: string, nodeName: string) => `node:${sliceName}/${nodeName}`;
  const netKey = (sliceName: string, netName: string) => `net:${sliceName}/${netName}`;

  const toggleItem = useCallback((key: string) => {
    setSelectedItems(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const clearSelection = useCallback(() => setSelectedItems(new Set()), []);

  // Count selected
  const selectedSliceNames = useMemo(() => {
    const names: string[] = [];
    for (const key of selectedItems) {
      if (key.startsWith('slice:')) names.push(key.slice(6));
    }
    return names;
  }, [selectedItems]);

  const selectedNodeKeys = useMemo(() => {
    const keys: Array<{ sliceName: string; nodeName: string }> = [];
    for (const key of selectedItems) {
      if (key.startsWith('node:')) {
        const rest = key.slice(5);
        const idx = rest.indexOf('/');
        if (idx >= 0) keys.push({ sliceName: rest.slice(0, idx), nodeName: rest.slice(idx + 1) });
      }
    }
    return keys;
  }, [selectedItems]);

  const selectedNetKeys = useMemo(() => {
    const keys: Array<{ sliceName: string; netName: string }> = [];
    for (const key of selectedItems) {
      if (key.startsWith('net:')) {
        const rest = key.slice(4);
        const idx = rest.indexOf('/');
        if (idx >= 0) keys.push({ sliceName: rest.slice(0, idx), netName: rest.slice(idx + 1) });
      }
    }
    return keys;
  }, [selectedItems]);

  const totalSelected = selectedItems.size;

  // --- Bulk delete ---

  const handleBulkDelete = useCallback(async () => {
    if (totalSelected === 0) return;
    const confirmMsg = `Delete ${selectedSliceNames.length} slice(s), ${selectedNodeKeys.length} node(s), and ${selectedNetKeys.length} network(s)?`;
    if (!window.confirm(confirmMsg)) return;
    setDeleting(true);
    try {
      // Delete whole slices
      for (const name of selectedSliceNames) {
        await onDeleteSlice(name);
        setSliceCache(prev => { const n = new Map(prev); n.delete(name); return n; });
      }
      // Delete individual nodes
      for (const { sliceName, nodeName } of selectedNodeKeys) {
        try {
          const data = await api.removeNode(sliceName, nodeName);
          setSliceCache(prev => { const n = new Map(prev); n.set(sliceName, data); return n; });
        } catch { /* ignore */ }
      }
      // Delete individual networks
      for (const { sliceName, netName } of selectedNetKeys) {
        try {
          const data = await api.removeNetwork(sliceName, netName);
          setSliceCache(prev => { const n = new Map(prev); n.set(sliceName, data); return n; });
        } catch { /* ignore */ }
      }
      clearSelection();
      onRefreshSlices();
    } finally {
      setDeleting(false);
    }
  }, [totalSelected, selectedSliceNames, selectedNodeKeys, selectedNetKeys, onDeleteSlice, clearSelection, onRefreshSlices]);

  // --- Filter + sort slices ---

  const lower = filterText.toLowerCase();

  const filteredSlices = useMemo(() => {
    if (!filterText) return slices;
    return slices.filter(s => {
      if (s.name.toLowerCase().includes(lower)) return true;
      if (s.state.toLowerCase().includes(lower)) return true;
      // Also check cached child data
      const cached = sliceCache.get(s.name);
      if (cached) {
        for (const node of cached.nodes) {
          if (node.name.toLowerCase().includes(lower)) return true;
          if ((node.site || '').toLowerCase().includes(lower)) return true;
          if ((node.image || '').toLowerCase().includes(lower)) return true;
        }
        for (const net of cached.networks) {
          if (net.name.toLowerCase().includes(lower)) return true;
        }
      }
      return false;
    });
  }, [slices, filterText, lower, sliceCache]);

  const sortedSlices = useMemo(() => {
    const sorted = [...filteredSlices];
    sorted.sort((a, b) => {
      let av: string | number = '';
      let bv: string | number = '';
      switch (sliceSort) {
        case 'name': av = a.name.toLowerCase(); bv = b.name.toLowerCase(); break;
        case 'state': av = a.state.toLowerCase(); bv = b.state.toLowerCase(); break;
        case 'lease_end': {
          const ca = sliceCache.get(a.name);
          const cb = sliceCache.get(b.name);
          av = ca?.lease_end || '';
          bv = cb?.lease_end || '';
          break;
        }
        case 'nodes': {
          av = sliceCache.get(a.name)?.nodes.length ?? -1;
          bv = sliceCache.get(b.name)?.nodes.length ?? -1;
          break;
        }
        case 'networks': {
          av = sliceCache.get(a.name)?.networks.length ?? -1;
          bv = sliceCache.get(b.name)?.networks.length ?? -1;
          break;
        }
      }
      if (typeof av === 'number' && typeof bv === 'number') {
        return sliceSortDir === 'asc' ? av - bv : bv - av;
      }
      if (av < bv) return sliceSortDir === 'asc' ? -1 : 1;
      if (av > bv) return sliceSortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [filteredSlices, sliceSort, sliceSortDir, sliceCache]);

  const handleSliceHeaderClick = (key: typeof sliceSort) => {
    if (sliceSort === key) setSliceSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSliceSort(key); setSliceSortDir('asc'); }
  };

  const handleSliverHeaderClick = (key: typeof sliverSort) => {
    if (sliverSort === key) setSliverSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSliverSort(key); setSliverSortDir('asc'); }
  };

  const sortArrow = (key: string, active: string, dir: 'asc' | 'desc') =>
    <span className={`sort-arrow ${active === key ? 'active' : ''}`}>
      {active === key ? (dir === 'asc' ? '\u25B2' : '\u25BC') : '\u25B4'}
    </span>;

  const sortNodes = useCallback((nodes: SliceNode[]): SliceNode[] => {
    const sorted = [...nodes];
    sorted.sort((a, b) => {
      let av: string | number = '';
      let bv: string | number = '';
      switch (sliverSort) {
        case 'name': av = a.name.toLowerCase(); bv = b.name.toLowerCase(); break;
        case 'site': av = (a.site || '').toLowerCase(); bv = (b.site || '').toLowerCase(); break;
        case 'host': av = (a.host || '').toLowerCase(); bv = (b.host || '').toLowerCase(); break;
        case 'state': av = (a.reservation_state || '').toLowerCase(); bv = (b.reservation_state || '').toLowerCase(); break;
        case 'resources': av = (a.cores ?? 0) * 1000 + (a.ram ?? 0) * 10 + (a.disk ?? 0); bv = (b.cores ?? 0) * 1000 + (b.ram ?? 0) * 10 + (b.disk ?? 0); break;
        case 'ip': av = a.management_ip || ''; bv = b.management_ip || ''; break;
      }
      if (typeof av === 'number' && typeof bv === 'number') return sliverSortDir === 'asc' ? av - bv : bv - av;
      if (av < bv) return sliverSortDir === 'asc' ? -1 : 1;
      if (av > bv) return sliverSortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [sliverSort, sliverSortDir]);

  const sortNets = useCallback((nets: SliceNetwork[]): SliceNetwork[] => {
    const sorted = [...nets];
    sorted.sort((a, b) => {
      const av = a.name.toLowerCase();
      const bv = b.name.toLowerCase();
      if (av < bv) return sliverSortDir === 'asc' ? -1 : 1;
      if (av > bv) return sliverSortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [sliverSortDir]);

  // --- Context menu ---

  const handleSliceContextMenu = useCallback((e: React.MouseEvent, sliceName: string) => {
    e.preventDefault();
    if (!onContextAction) return;
    setMenu({ x: e.clientX, y: e.clientY, rows: [], sliceNames: [sliceName] });
  }, [onContextAction]);

  const handleNodeContextMenu = useCallback((e: React.MouseEvent, sliceName: string, node: Record<string, string>) => {
    e.preventDefault();
    if (!onContextAction) return;
    setMenu({ x: e.clientX, y: e.clientY, rows: [node], sliceNames: [sliceName] });
  }, [onContextAction]);

  const renderContextMenu = () => {
    if (!menu || !onContextAction) return null;
    const { rows, sliceNames } = menu;
    const hasSlices = sliceNames && sliceNames.length > 0;
    const singleNode = rows.length === 1 && rows[0].element_type === 'node' ? rows[0] : null;
    const vmsWithIp = rows.filter(r => r.element_type === 'node' && r.management_ip);

    // Compatible recipes (single VM with IP only)
    let compatibleRecipes: RecipeSummary[] = [];
    if (singleNode && singleNode.management_ip && recipes && recipes.length > 0) {
      const vmImage = singleNode.image || '';
      compatibleRecipes = recipes.filter((r) => {
        const patterns = r.image_patterns || {};
        return Object.keys(patterns).some((key) =>
          key === '*' || vmImage.toLowerCase().includes(key.toLowerCase())
        );
      });
    }

    return (
      <div
        className="graph-context-menu"
        style={{ left: menu.x, top: menu.y }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Open in Editor */}
        {hasSlices && sliceNames!.length === 1 && (
          <button
            className="graph-context-menu-item"
            onClick={() => {
              const entry = slices.find(s => s.name === sliceNames![0]);
              onSliceSelect(entry?.id || sliceNames![0]);
              setMenu(null);
            }}
          >
            {'\u270E'} Open in Editor
          </button>
        )}

        {/* Open Build Log */}
        {hasSlices && sliceNames!.length === 1 && (
          <button
            className="graph-context-menu-item"
            onClick={() => {
              onContextAction({ type: 'open-boot-log', elements: [], sliceNames });
              setMenu(null);
            }}
          >
            {'\u2630'} Open Build Log
          </button>
        )}

        {/* Open Terminal */}
        {vmsWithIp.length > 0 && (
          <button
            className="graph-context-menu-item"
            onClick={() => {
              onContextAction({ type: 'terminal', elements: vmsWithIp });
              setMenu(null);
            }}
          >
            {'\uD83D\uDCBB'} Open Terminal{vmsWithIp.length > 1 ? ` (${vmsWithIp.length})` : ''}
          </button>
        )}

        {/* Save as VM Template — single VM only */}
        {singleNode && (
          <button
            className="graph-context-menu-item"
            onClick={() => {
              onContextAction({ type: 'save-vm-template', elements: [singleNode], nodeName: singleNode.name });
              setMenu(null);
            }}
          >
            {'\uD83D\uDCBE'} Save as VM Template
          </button>
        )}

        {/* Recipes */}
        {compatibleRecipes.length > 0 && (
          <>
            <div className="graph-context-menu-sep" />
            <div className="graph-context-menu-label">Recipes</div>
            {compatibleRecipes.map((r) => (
              <button
                key={r.dir_name}
                className="graph-context-menu-item"
                onClick={() => {
                  onContextAction({ type: 'apply-recipe', elements: [singleNode!], nodeName: singleNode!.name, recipeName: r.dir_name });
                  setMenu(null);
                }}
              >
                {'\uD83D\uDCDC'} {r.name}
              </button>
            ))}
          </>
        )}

        <div className="graph-context-menu-sep" />

        {/* Delete slice */}
        {hasSlices && (
          <button
            className="graph-context-menu-item danger"
            onClick={() => {
              onContextAction({ type: 'delete-slice', elements: [], sliceNames });
              setMenu(null);
            }}
          >
            {'\uD83D\uDDD1'} Delete Slice{sliceNames!.length > 1 ? ` (${sliceNames!.length})` : ''}
          </button>
        )}

        {/* Delete node/network */}
        {rows.length > 0 && !hasSlices && (
          <button
            className="graph-context-menu-item danger"
            onClick={() => {
              onContextAction({ type: 'delete', elements: rows });
              setMenu(null);
            }}
          >
            {'\uD83D\uDDD1'} Delete{rows.length > 1 ? ` (${rows.length})` : ''}
          </button>
        )}
      </div>
    );
  };

  // --- Filter child slivers within expanded slices ---

  const filterNode = useCallback((node: { name: string; site?: string; host?: string; image?: string; reservation_state?: string; management_ip?: string }) => {
    if (!filterText) return true;
    return (
      node.name.toLowerCase().includes(lower) ||
      (node.site || '').toLowerCase().includes(lower) ||
      (node.host || '').toLowerCase().includes(lower) ||
      (node.image || '').toLowerCase().includes(lower) ||
      (node.reservation_state || '').toLowerCase().includes(lower) ||
      (node.management_ip || '').toLowerCase().includes(lower)
    );
  }, [filterText, lower]);

  const filterNet = useCallback((net: { name: string; type?: string; layer?: string; subnet?: string }) => {
    if (!filterText) return true;
    return (
      net.name.toLowerCase().includes(lower) ||
      (net.type || '').toLowerCase().includes(lower) ||
      (net.layer || '').toLowerCase().includes(lower) ||
      (net.subnet || '').toLowerCase().includes(lower)
    );
  }, [filterText, lower]);

  // --- Render ---

  if (slices.length === 0) {
    return (
      <div className="all-slivers-view">
        <div className="sliver-empty">No slices available</div>
      </div>
    );
  }

  return (
    <div className="all-slivers-view">
      {/* Action / filter bar */}
      <div className="sliver-action-bar">
        <Tooltip text="Filter slices by name, state, site, or image. Use with Select All for bulk operations.">
          <input
            type="text"
            className="sliver-action-filter"
            placeholder="Filter by name, state, site, image..."
            value={filterText}
            onChange={e => setFilterText(e.target.value)}
            data-help-id="sliver.table"
          />
        </Tooltip>
        <span className="sliver-filter-count">
          {filteredSlices.length} of {slices.length} slices
        </span>
        <Tooltip text="Select all filtered slices for bulk delete or other operations">
          <button
            className="sliver-action-btn"
            onClick={() => {
              const allKeys = new Set(selectedItems);
              for (const s of filteredSlices) allKeys.add(sliceKey(s.name));
              setSelectedItems(allKeys);
            }}
            data-help-id="sliver.select-all"
          >
            Select All ({filteredSlices.length})
          </button>
        </Tooltip>
        {totalSelected > 0 && (
          <span className="sliver-selection-actions">
            <span className="sliver-selection-count">{totalSelected} selected</span>
            <Tooltip text="Delete all selected slices, nodes, and networks">
              <button
                className="sliver-action-btn danger"
                onClick={handleBulkDelete}
                disabled={deleting}
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </Tooltip>
            <Tooltip text="Deselect all items">
              <button className="sliver-action-btn" onClick={clearSelection}>
                Clear
              </button>
            </Tooltip>
          </span>
        )}
      </div>

      {/* Table */}
      <div className="sliver-table-wrapper">
        <table className="sliver-table all-sliver-table">
          <thead>
            <tr>
              <th className="sliver-checkbox-col" style={{ width: 28 }}>
                <Tooltip text="Toggle selection of all filtered slices">
                  <input
                    type="checkbox"
                    checked={filteredSlices.length > 0 && filteredSlices.every(s => selectedItems.has(sliceKey(s.name)))}
                    onChange={(e) => {
                      const next = new Set(selectedItems);
                      if (e.target.checked) {
                        for (const s of filteredSlices) next.add(sliceKey(s.name));
                      } else {
                        for (const s of filteredSlices) next.delete(sliceKey(s.name));
                      }
                      setSelectedItems(next);
                    }}
                  />
                </Tooltip>
              </th>
              <th className="slice-expand-col" style={{ width: 28 }}></th>
              <th onClick={() => handleSliceHeaderClick('name')}>
                Slice Name {sortArrow('name', sliceSort, sliceSortDir)}
              </th>
              <th onClick={() => handleSliceHeaderClick('state')}>
                State {sortArrow('state', sliceSort, sliceSortDir)}
              </th>
              <th onClick={() => handleSliceHeaderClick('lease_end')}>
                Lease End {sortArrow('lease_end', sliceSort, sliceSortDir)}
              </th>
              <th onClick={() => handleSliceHeaderClick('nodes')}>
                Nodes {sortArrow('nodes', sliceSort, sliceSortDir)}
              </th>
              <th onClick={() => handleSliceHeaderClick('networks')}>
                Networks {sortArrow('networks', sliceSort, sliceSortDir)}
              </th>
              <th>Errors</th>
            </tr>
          </thead>
          <tbody>
            {sortedSlices.map((slice, sliceIndex) => {
              const isExpanded = expandedSlices.has(slice.name);
              const isLoading = loadingSlices.has(slice.name);
              const cached = sliceCache.get(slice.name);
              const sk = sliceKey(slice.name);
              const sliceChecked = selectedItems.has(sk);
              const groupClass = sliceIndex % 2 === 0 ? 'slice-group-even' : 'slice-group-odd';

              const nodeCount = cached?.nodes.length ?? '?';
              const netCount = cached?.networks.length ?? '?';
              const errorCount = cached?.error_messages?.length ?? (slice.has_errors ? '!' : 0);

              // Filter and sort child slivers
              const filteredNodes = cached ? sortNodes(cached.nodes.filter(filterNode)) : [];
              const filteredNets = cached ? sortNets(cached.networks.filter(filterNet)) : [];

              return [
                // Slice row
                <tr
                  key={slice.name}
                  className={`slice-row ${sliceChecked ? 'multi-selected' : ''}`}
                  onContextMenu={(e) => handleSliceContextMenu(e, slice.name)}
                  onDoubleClick={() => onSliceSelect(slice.id)}
                >
                  <td className="sliver-checkbox-col" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={sliceChecked}
                      onChange={() => toggleItem(sk)}
                    />
                  </td>
                  <td className="slice-expand-col">
                    <button
                      className={`slice-expand-btn ${isExpanded ? 'expanded' : ''}`}
                      onClick={(e) => { e.stopPropagation(); toggleExpand(slice.name); }}
                      title={isExpanded ? 'Collapse' : 'Expand'}
                    >
                      {isLoading ? '\u21BB' : '\u25B6'}
                    </button>
                  </td>
                  <td className="slice-name-cell" onClick={() => onSliceSelect(slice.id)} title={slice.name}>
                    {slice.name}
                  </td>
                  <td>
                    <span className={`sliver-state-badge ${stateClass(slice.state)}`}>{slice.state}</span>
                  </td>
                  <td>{cached ? formatLeaseEnd(cached.lease_end) : <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                  <td>{nodeCount}</td>
                  <td>{netCount}</td>
                  <td>
                    {errorCount === 0 ? (
                      <span className="sliver-cell-muted">0</span>
                    ) : (
                      <span className="sliver-error-count">{errorCount}</span>
                    )}
                    <button
                      className="slice-refresh-btn"
                      onClick={(e) => { e.stopPropagation(); refreshSliceCache(slice.name); }}
                      title="Refresh slice data"
                      disabled={isLoading}
                    >
                      {'\u21BB'}
                    </button>
                  </td>
                </tr>,

                // Expanded child rows
                ...(isExpanded ? [
                  // Failed to load
                  ...(isLoading && !cached ? [
                    <tr key={`${slice.name}-loading`} className={`sliver-section-header ${groupClass}`}>
                      <td colSpan={8} style={{ textAlign: 'center', fontStyle: 'italic' }}>Loading...</td>
                    </tr>
                  ] : []),

                  // VMs sub-header
                  ...(cached && filteredNodes.length > 0 ? [
                    <tr key={`${slice.name}-vm-header`} className={`sliver-section-header ${groupClass}`}>
                      <td colSpan={8}>
                        <span className="sliver-type-badge node">VM</span> Nodes ({filteredNodes.length})
                      </td>
                    </tr>,
                    // Mini sort header for node columns (only when >1 node)
                    ...(filteredNodes.length > 1 ? [
                      <tr key={`${slice.name}-vm-sort`} className={`sliver-sort-header ${groupClass}`}>
                        <td className="sliver-checkbox-col"></td>
                        <td></td>
                        <td className="sliver-indent" onClick={() => handleSliverHeaderClick('name')}>
                          Name {sortArrow('name', sliverSort, sliverSortDir)}
                        </td>
                        <td onClick={() => handleSliverHeaderClick('site')}>
                          Site {sortArrow('site', sliverSort, sliverSortDir)}
                        </td>
                        <td onClick={() => handleSliverHeaderClick('host')}>
                          Host {sortArrow('host', sliverSort, sliverSortDir)}
                        </td>
                        <td onClick={() => handleSliverHeaderClick('state')}>
                          State {sortArrow('state', sliverSort, sliverSortDir)}
                        </td>
                        <td onClick={() => handleSliverHeaderClick('resources')}>
                          Resources {sortArrow('resources', sliverSort, sliverSortDir)}
                        </td>
                        <td onClick={() => handleSliverHeaderClick('ip')}>
                          IP {sortArrow('ip', sliverSort, sliverSortDir)}
                        </td>
                      </tr>
                    ] : []),
                    ...filteredNodes.map(node => {
                      const nk = nodeKey(slice.name, node.name);
                      const checked = selectedItems.has(nk);
                      const clickData: Record<string, string> = {
                        element_type: 'node',
                        name: node.name,
                        site: node.site || '',
                        cores: String(node.cores ?? ''),
                        ram: String(node.ram ?? ''),
                        disk: String(node.disk ?? ''),
                        image: node.image || '',
                        reservation_state: node.reservation_state || '',
                        management_ip: node.management_ip || '',
                      };
                      return (
                        <tr
                          key={`${slice.name}-node-${node.name}`}
                          className={`sliver-row ${groupClass} ${checked ? 'multi-selected' : ''}`}
                          onContextMenu={(e) => handleNodeContextMenu(e, slice.name, clickData)}
                        >
                          <td className="sliver-checkbox-col" onClick={e => e.stopPropagation()}>
                            <input type="checkbox" checked={checked} onChange={() => toggleItem(nk)} />
                          </td>
                          <td></td>
                          <td className="sliver-indent" title={node.name}>{node.name}</td>
                          <td>{node.site || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                          <td title={node.host || ''}>{node.host || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                          <td>
                            {node.reservation_state ? (
                              <span className={`sliver-state-badge ${stateClass(node.reservation_state)}`}>{node.reservation_state}</span>
                            ) : (
                              <span className="sliver-cell-muted">{'\u2014'}</span>
                            )}
                          </td>
                          <td>{node.cores ?? ''}{node.ram ? ` / ${node.ram}G` : ''}{node.disk ? ` / ${node.disk}G` : ''}</td>
                          <td title={node.management_ip || ''}>{node.management_ip || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                        </tr>
                      );
                    })
                  ] : []),

                  // Networks sub-header
                  ...(cached && filteredNets.length > 0 ? [
                    <tr key={`${slice.name}-net-header`} className={`sliver-section-header ${groupClass}`}>
                      <td colSpan={8}>
                        <span className="sliver-type-badge network">Net</span> Networks ({filteredNets.length})
                      </td>
                    </tr>,
                    ...filteredNets.map(net => {
                      const nk = netKey(slice.name, net.name);
                      const checked = selectedItems.has(nk);
                      return (
                        <tr
                          key={`${slice.name}-net-${net.name}`}
                          className={`sliver-row ${groupClass} ${checked ? 'multi-selected' : ''}`}
                        >
                          <td className="sliver-checkbox-col" onClick={e => e.stopPropagation()}>
                            <input type="checkbox" checked={checked} onChange={() => toggleItem(nk)} />
                          </td>
                          <td></td>
                          <td className="sliver-indent" title={net.name}>{net.name}</td>
                          <td>{[net.layer, net.type].filter(Boolean).join(' / ') || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                          <td>{net.subnet || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                          <td>{net.gateway || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                          <td>{net.interfaces?.length ?? 0}</td>
                          <td></td>
                        </tr>
                      );
                    })
                  ] : []),

                  // Empty expanded state
                  ...(cached && filteredNodes.length === 0 && filteredNets.length === 0 ? [
                    <tr key={`${slice.name}-empty`} className={`sliver-section-header ${groupClass}`}>
                      <td colSpan={8} style={{ textAlign: 'center', fontStyle: 'italic' }}>
                        {cached.nodes.length === 0 && cached.networks.length === 0 ? 'No slivers in this slice' : 'No matches in this slice'}
                      </td>
                    </tr>
                  ] : []),
                ] : []),
              ];
            })}
          </tbody>
        </table>
      </div>

      {/* Context menu */}
      {renderContextMenu()}
    </div>
  );
});
