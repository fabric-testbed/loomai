'use client';
import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import type { SliceData, RecipeSummary } from '../types/fabric';
import type { ContextMenuAction } from './CytoscapeGraph';
import '../styles/sliver-view.css';
import '../styles/context-menu.css';

interface SliverViewProps {
  sliceData: SliceData | null;
  selectedElement: Record<string, string> | null;
  onRowClick: (data: Record<string, string>) => void;
  onBackgroundClick: () => void;
  dark: boolean;
  nodeActivity?: Record<string, string>;
  onContextAction?: (action: ContextMenuAction) => void;
  recipes?: RecipeSummary[];
}

// --- VM rows ---

interface VMRow {
  type: string;
  name: string;
  site: string;
  host: string;
  state: string;
  cores: string;
  ram: string;
  disk: string;
  image: string;
  mgmtIp: string;
  components: string;
  interfaces: string;
  clickData: Record<string, string>;
}

type VMSortKey = keyof Pick<VMRow, 'type' | 'name' | 'site' | 'host' | 'state' | 'cores' | 'ram' | 'disk' | 'image' | 'mgmtIp' | 'components' | 'interfaces'>;

const VM_COLUMNS: { key: VMSortKey; label: string }[] = [
  { key: 'type', label: 'Type' },
  { key: 'name', label: 'Name' },
  { key: 'site', label: 'Site' },
  { key: 'host', label: 'Host' },
  { key: 'state', label: 'State' },
  { key: 'cores', label: 'Cores' },
  { key: 'ram', label: 'RAM' },
  { key: 'disk', label: 'Disk' },
  { key: 'image', label: 'Image' },
  { key: 'mgmtIp', label: 'Mgmt IP' },
  { key: 'components', label: 'Components' },
  { key: 'interfaces', label: 'Interfaces' },
];

// --- Network rows ---

interface NetRow {
  type: 'network' | 'facility-port';
  typeLabel: string;
  name: string;
  site: string;
  layerType: string;
  subnet: string;
  gateway: string;
  interfaces: string;
  interfaceList: string;
  clickData: Record<string, string>;
}

type NetSortKey = keyof Pick<NetRow, 'type' | 'name' | 'site' | 'layerType' | 'subnet' | 'gateway' | 'interfaces' | 'interfaceList'>;

const NET_COLUMNS: { key: NetSortKey; label: string }[] = [
  { key: 'type', label: 'Type' },
  { key: 'name', label: 'Name' },
  { key: 'site', label: 'Site' },
  { key: 'layerType', label: 'Layer / Type' },
  { key: 'subnet', label: 'Subnet' },
  { key: 'gateway', label: 'Gateway' },
  { key: 'interfaces', label: 'Ifaces' },
  { key: 'interfaceList', label: 'Connected Interfaces' },
];

// --- Context menu state ---

interface MenuState {
  x: number;
  y: number;
  rows: Record<string, string>[];
}

// --- Shared helpers ---

function stateClass(state: string): string {
  const s = state.toLowerCase();
  if (s.includes('active')) return 'active';
  if (s.includes('configuring')) return 'configuring';
  if (s.includes('nascent')) return 'nascent';
  if (s.includes('closing')) return 'closing';
  if (s.includes('dead')) return 'dead';
  if (s.includes('ticketed')) return 'ticketed';
  if (s.includes('allocat')) return 'allocating';
  return '';
}

function genericSort<T>(rows: T[], column: keyof T, direction: 'asc' | 'desc', numericKeys: string[]): T[] {
  const sorted = [...rows];
  sorted.sort((a, b) => {
    const av = String(a[column] ?? '');
    const bv = String(b[column] ?? '');
    if (numericKeys.includes(column as string)) {
      const an = parseFloat(av) || 0;
      const bn = parseFloat(bv) || 0;
      return direction === 'asc' ? an - bn : bn - an;
    }
    const al = av.toLowerCase();
    const bl = bv.toLowerCase();
    if (al < bl) return direction === 'asc' ? -1 : 1;
    if (al > bl) return direction === 'asc' ? 1 : -1;
    return 0;
  });
  return sorted;
}

// --- Main component ---

export default function SliverView({ sliceData, selectedElement, onRowClick, onBackgroundClick, nodeActivity, onContextAction, recipes }: SliverViewProps) {
  const [vmSort, setVmSort] = useState<VMSortKey>('name');
  const [vmDir, setVmDir] = useState<'asc' | 'desc'>('asc');
  const [netSort, setNetSort] = useState<NetSortKey>('name');
  const [netDir, setNetDir] = useState<'asc' | 'desc'>('asc');
  const [filterText, setFilterText] = useState('');

  // Multi-selection state
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set());
  const lastClickedIndexRef = useRef<number | null>(null);

  // Context menu state
  const [menu, setMenu] = useState<MenuState | null>(null);

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

  // Vertical resize: split percentage for VM panel (0-100)
  const [vmPct, setVmPct] = useState(60);
  const panelsRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    const startY = e.clientY;
    const startPct = vmPct;
    const container = panelsRef.current;
    if (!container) return;
    const containerHeight = container.getBoundingClientRect().height;

    const onMove = (ev: MouseEvent) => {
      if (!draggingRef.current) return;
      const delta = ev.clientY - startY;
      const deltaPct = (delta / containerHeight) * 100;
      const newPct = Math.min(85, Math.max(15, startPct + deltaPct));
      setVmPct(newPct);
    };
    const onUp = () => {
      draggingRef.current = false;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }, [vmPct]);

  // Build VM rows
  const vmRows = useMemo<VMRow[]>(() => {
    if (!sliceData) return [];
    return sliceData.nodes.map(node => ({
      type: 'VM',
      name: node.name,
      site: node.site || '',
      host: node.host || '',
      state: node.reservation_state || '',
      cores: String(node.cores ?? ''),
      ram: node.ram ? `${node.ram} GB` : '',
      disk: node.disk ? `${node.disk} GB` : '',
      image: node.image || '',
      mgmtIp: node.management_ip || '',
      components: node.components?.map(c => `${c.name} (${c.model})`).join(', ') || '',
      interfaces: String(node.interfaces?.length ?? 0),
      clickData: {
        element_type: 'node',
        name: node.name,
        site: node.site || '',
        cores: String(node.cores ?? ''),
        ram: String(node.ram ?? ''),
        disk: String(node.disk ?? ''),
        image: node.image || '',
        reservation_state: node.reservation_state || '',
        management_ip: node.management_ip || '',
      },
    }));
  }, [sliceData]);

  // Build network + facility port rows
  const netRows = useMemo<NetRow[]>(() => {
    if (!sliceData) return [];
    const result: NetRow[] = [];
    for (const net of sliceData.networks) {
      result.push({
        type: 'network',
        typeLabel: 'Net',
        name: net.name,
        site: '',
        layerType: [net.layer, net.type].filter(Boolean).join(' / '),
        subnet: net.subnet || '',
        gateway: net.gateway || '',
        interfaces: String(net.interfaces?.length ?? 0),
        interfaceList: net.interfaces?.map(i => `${i.node_name}:${i.network_name}`).join(', ') || '',
        clickData: {
          element_type: 'network',
          name: net.name,
          layer: net.layer || '',
          type: net.type || '',
          subnet: net.subnet || '',
          gateway: net.gateway || '',
        },
      });
    }
    for (const fp of (sliceData.facility_ports ?? [])) {
      result.push({
        type: 'facility-port',
        typeLabel: 'FP',
        name: fp.name,
        site: fp.site || '',
        layerType: fp.bandwidth || '',
        subnet: '',
        gateway: '',
        interfaces: String(fp.interfaces?.length ?? 0),
        interfaceList: fp.interfaces?.map(i => `${i.node_name}:${i.network_name}`).join(', ') || '',
        clickData: {
          element_type: 'facility_port',
          name: fp.name,
          site: fp.site || '',
          vlan: fp.vlan || '',
          bandwidth: fp.bandwidth || '',
        },
      });
    }
    return result;
  }, [sliceData]);

  // Filter
  const lower = filterText.toLowerCase();
  const filteredVMs = useMemo(() => {
    if (!filterText) return vmRows;
    return vmRows.filter(r =>
      r.name.toLowerCase().includes(lower) ||
      r.site.toLowerCase().includes(lower) ||
      r.host.toLowerCase().includes(lower) ||
      r.state.toLowerCase().includes(lower) ||
      r.image.toLowerCase().includes(lower)
    );
  }, [vmRows, lower, filterText]);

  const filteredNets = useMemo(() => {
    if (!filterText) return netRows;
    return netRows.filter(r =>
      r.name.toLowerCase().includes(lower) ||
      r.site.toLowerCase().includes(lower) ||
      r.layerType.toLowerCase().includes(lower) ||
      r.typeLabel.toLowerCase().includes(lower)
    );
  }, [netRows, lower, filterText]);

  // Sort
  const sortedVMs = useMemo(() =>
    genericSort(filteredVMs, vmSort, vmDir, ['cores', 'ram', 'disk', 'interfaces']),
    [filteredVMs, vmSort, vmDir]);

  const sortedNets = useMemo(() =>
    genericSort(filteredNets, netSort, netDir, ['interfaces']),
    [filteredNets, netSort, netDir]);

  const handleVmHeader = (key: VMSortKey) => {
    if (vmSort === key) setVmDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setVmSort(key); setVmDir('asc'); }
  };

  const handleNetHeader = (key: NetSortKey) => {
    if (netSort === key) setNetDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setNetSort(key); setNetDir('asc'); }
  };

  const isSelected = (clickData: Record<string, string>) =>
    selectedElement?.name === clickData.name && selectedElement?.element_type === clickData.element_type;

  // --- Multi-selection handlers ---

  const handleVmRowClick = useCallback((e: React.MouseEvent, row: VMRow, index: number) => {
    if (e.ctrlKey || e.metaKey) {
      // Toggle individual checkbox
      setSelectedNames(prev => {
        const next = new Set(prev);
        if (next.has(row.name)) next.delete(row.name);
        else next.add(row.name);
        return next;
      });
      lastClickedIndexRef.current = index;
    } else if (e.shiftKey && lastClickedIndexRef.current !== null) {
      // Range select
      const start = Math.min(lastClickedIndexRef.current, index);
      const end = Math.max(lastClickedIndexRef.current, index);
      const rangeNames = sortedVMs.slice(start, end + 1).map(r => r.name);
      setSelectedNames(prev => {
        const next = new Set(prev);
        for (const n of rangeNames) next.add(n);
        return next;
      });
    } else {
      // Plain click — single select for editor panel, clear multi-select
      setSelectedNames(new Set());
      lastClickedIndexRef.current = index;
      onRowClick(row.clickData);
    }
  }, [sortedVMs, onRowClick]);

  const handleSelectAll = useCallback(() => {
    if (selectedNames.size === sortedVMs.length) {
      setSelectedNames(new Set());
    } else {
      setSelectedNames(new Set(sortedVMs.map(r => r.name)));
    }
  }, [sortedVMs, selectedNames.size]);

  // --- Context menu handlers ---

  const handleVmContextMenu = useCallback((e: React.MouseEvent, row: VMRow) => {
    e.preventDefault();
    if (!onContextAction) return;
    // If right-clicking a multi-selected row, use all selected
    let contextRows: Record<string, string>[];
    if (selectedNames.has(row.name) && selectedNames.size > 1) {
      contextRows = sortedVMs.filter(r => selectedNames.has(r.name)).map(r => r.clickData);
    } else {
      contextRows = [row.clickData];
    }
    setMenu({ x: e.clientX, y: e.clientY, rows: contextRows });
  }, [onContextAction, selectedNames, sortedVMs]);

  const handleNetContextMenu = useCallback((e: React.MouseEvent, row: NetRow) => {
    e.preventDefault();
    if (!onContextAction) return;
    setMenu({ x: e.clientX, y: e.clientY, rows: [row.clickData] });
  }, [onContextAction]);

  // --- Render context menu ---

  const renderContextMenu = () => {
    if (!menu || !onContextAction) return null;

    const rows = menu.rows;
    const isMulti = rows.length > 1;
    const allVMs = rows.every(r => r.element_type === 'node');
    const singleVM = allVMs && rows.length === 1 ? rows[0] : null;
    const vmsWithIp = rows.filter(r => r.element_type === 'node' && r.management_ip);

    // Compatible recipes (single VM with IP only)
    let compatibleRecipes: RecipeSummary[] = [];
    if (singleVM && singleVM.management_ip && recipes && recipes.length > 0) {
      const vmImage = singleVM.image || '';
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
        {/* Open Terminal */}
        {vmsWithIp.length > 0 && (
          <button
            className="graph-context-menu-item"
            onClick={() => {
              onContextAction({ type: 'terminal', elements: vmsWithIp });
              setMenu(null);
            }}
          >
            {'\u{1F4BB}'} Open Terminal{vmsWithIp.length > 1 ? ` (${vmsWithIp.length})` : ''}
          </button>
        )}

        {/* Save as VM Template — single VM only */}
        {singleVM && (
          <button
            className="graph-context-menu-item"
            onClick={() => {
              onContextAction({ type: 'save-vm-template', elements: [singleVM], nodeName: singleVM.name });
              setMenu(null);
            }}
          >
            {'\uD83D\uDCBE'} Save as VM Template
          </button>
        )}

        {/* Recipes — single VM with IP only */}
        {compatibleRecipes.length > 0 && (
          <>
            <div className="graph-context-menu-sep" />
            <div className="graph-context-menu-label">Recipes</div>
            {compatibleRecipes.map((r) => (
              <button
                key={r.dir_name}
                className="graph-context-menu-item"
                onClick={() => {
                  onContextAction({ type: 'apply-recipe', elements: [singleVM!], nodeName: singleVM!.name, recipeName: r.dir_name });
                  setMenu(null);
                }}
              >
                {'\u{1F4DC}'} {r.name}
              </button>
            ))}
          </>
        )}

        {/* Separator before delete */}
        <div className="graph-context-menu-sep" />

        {/* Delete */}
        <button
          className="graph-context-menu-item danger"
          onClick={() => {
            onContextAction({ type: 'delete', elements: rows });
            setMenu(null);
          }}
        >
          {'\uD83D\uDDD1'} Delete{isMulti ? ` (${rows.length})` : ''}
        </button>
      </div>
    );
  };

  if (!sliceData) {
    return <div className="sliver-view"><div className="sliver-empty">No slice loaded</div></div>;
  }

  if (vmRows.length === 0 && netRows.length === 0) {
    return <div className="sliver-view"><div className="sliver-empty">No slivers in this slice</div></div>;
  }

  const totalCount = vmRows.length + netRows.length;
  const filteredCount = filteredVMs.length + filteredNets.length;

  return (
    <div className="sliver-view" onClick={(e) => { if (e.target === e.currentTarget) onBackgroundClick(); }} data-help-id="sliver.table">
      <div className="sliver-filter">
        <input
          type="text"
          placeholder="Filter by name, site, state, image..."
          value={filterText}
          onChange={e => setFilterText(e.target.value)}
        />
        <span className="sliver-filter-count">
          {filteredCount} of {totalCount}
        </span>
      </div>

      <div className="sliver-panels" ref={panelsRef}>
        {/* VM Panel */}
        <div className="sliver-panel" style={{ flex: `0 0 calc(${vmPct}% - 3px)` }}>
          <div className="sliver-panel-header">
            <span className="sliver-panel-title">
              <span className="sliver-type-badge node">VM</span> Nodes
              <span className="sliver-panel-count">{filteredVMs.length}</span>
            </span>
          </div>
          {filteredVMs.length === 0 ? (
            <div className="sliver-panel-empty">{vmRows.length === 0 ? 'No VM nodes' : 'No matches'}</div>
          ) : (
            <div className="sliver-table-wrapper">
              <table className="sliver-table">
                <thead>
                  <tr>
                    <th className="sliver-checkbox-col">
                      <input
                        type="checkbox"
                        checked={selectedNames.size === sortedVMs.length && sortedVMs.length > 0}
                        onChange={handleSelectAll}
                        title="Select all"
                      />
                    </th>
                    {VM_COLUMNS.map(col => (
                      <th key={col.key} onClick={() => handleVmHeader(col.key)}>
                        {col.label}
                        <span className={`sort-arrow ${vmSort === col.key ? 'active' : ''}`}>
                          {vmSort === col.key ? (vmDir === 'asc' ? '\u25B2' : '\u25BC') : '\u25B4'}
                        </span>
                      </th>
                    ))}
                    <th>Activity</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedVMs.map((row, idx) => {
                    const multiSelected = selectedNames.has(row.name);
                    return (
                      <tr
                        key={row.name}
                        className={`${isSelected(row.clickData) ? 'selected' : ''} ${multiSelected ? 'multi-selected' : ''}`}
                        onClick={(e) => handleVmRowClick(e, row, idx)}
                        onContextMenu={(e) => handleVmContextMenu(e, row)}
                      >
                        <td className="sliver-checkbox-col" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={multiSelected}
                            onChange={() => {
                              setSelectedNames(prev => {
                                const next = new Set(prev);
                                if (next.has(row.name)) next.delete(row.name);
                                else next.add(row.name);
                                return next;
                              });
                            }}
                          />
                        </td>
                        <td><span className="sliver-type-badge node">{row.type}</span></td>
                        <td title={row.name}>{row.name}</td>
                        <td>{row.site || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                        <td title={row.host}>{row.host || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                        <td>
                          {row.state
                            ? <span className={`sliver-state-badge ${stateClass(row.state)}`}>{row.state}</span>
                            : <span className="sliver-cell-muted">{'\u2014'}</span>
                          }
                        </td>
                        <td>{row.cores || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                        <td>{row.ram || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                        <td>{row.disk || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                        <td title={row.image}>{row.image || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                        <td>{row.mgmtIp || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                        <td title={row.components}>{row.components || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                        <td>{row.interfaces || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                        <td>
                          {(() => {
                            const activity = nodeActivity?.[row.name];
                            if (!activity) return <span className="sliver-activity ready">Ready</span>;
                            const isFailed = activity.toLowerCase().includes('failed');
                            const isPending = activity.toLowerCase().includes('pending');
                            return (
                              <span className={`sliver-activity ${isFailed ? 'error' : isPending ? 'pending' : 'running'}`} title={activity}>
                                {!isFailed && !isPending && <span className="sliver-activity-spinner">{'\u21BB'}</span>}
                                {isFailed && <span>{'\u2717'} </span>}
                                {activity}
                              </span>
                            );
                          })()}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Resize handle */}
        <div className="sliver-resize-handle" onMouseDown={handleResizeStart}>
          <div className="sliver-resize-grip" />
        </div>

        {/* Network Services Panel */}
        <div className="sliver-panel" style={{ flex: `0 0 calc(${100 - vmPct}% - 3px)` }}>
          <div className="sliver-panel-header">
            <span className="sliver-panel-title">
              <span className="sliver-type-badge network">Net</span> Network Services
              <span className="sliver-panel-count">{filteredNets.length}</span>
            </span>
          </div>
          {filteredNets.length === 0 ? (
            <div className="sliver-panel-empty">{netRows.length === 0 ? 'No network services' : 'No matches'}</div>
          ) : (
            <div className="sliver-table-wrapper">
              <table className="sliver-table">
                <thead>
                  <tr>
                    {NET_COLUMNS.map(col => (
                      <th key={col.key} onClick={() => handleNetHeader(col.key)}>
                        {col.label}
                        <span className={`sort-arrow ${netSort === col.key ? 'active' : ''}`}>
                          {netSort === col.key ? (netDir === 'asc' ? '\u25B2' : '\u25BC') : '\u25B4'}
                        </span>
                      </th>
                    ))}
                    <th>Activity</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedNets.map(row => (
                    <tr
                      key={`${row.type}-${row.name}`}
                      className={isSelected(row.clickData) ? 'selected' : ''}
                      onClick={() => onRowClick(row.clickData)}
                      onContextMenu={(e) => handleNetContextMenu(e, row)}
                    >
                      <td><span className={`sliver-type-badge ${row.type}`}>{row.typeLabel}</span></td>
                      <td title={row.name}>{row.name}</td>
                      <td>{row.site || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                      <td>{row.layerType || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                      <td>{row.subnet || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                      <td>{row.gateway || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                      <td>{row.interfaces}</td>
                      <td title={row.interfaceList}>{row.interfaceList || <span className="sliver-cell-muted">{'\u2014'}</span>}</td>
                      <td>
                        {(() => {
                          const activity = nodeActivity?.[row.name];
                          if (!activity) return <span className="sliver-activity ready">Ready</span>;
                          const isFailed = activity.toLowerCase().includes('failed');
                          const isPending = activity.toLowerCase().includes('pending');
                          return (
                            <span className={`sliver-activity ${isFailed ? 'error' : isPending ? 'pending' : 'running'}`} title={activity}>
                              {!isFailed && !isPending && <span className="sliver-activity-spinner">{'\u21BB'}</span>}
                              {isFailed && <span>{'\u2717'} </span>}
                              {activity}
                            </span>
                          );
                        })()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Context menu overlay */}
      {renderContextMenu()}
    </div>
  );
}
