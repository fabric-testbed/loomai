'use client';
import React, { useState, useMemo } from 'react';
import type { FacilityPortInfo } from '../types/fabric';

interface FacilityPortsBrowserProps {
  facilityPorts: FacilityPortInfo[];
  loading: boolean;
}

/** Expand a VLAN range string like "800-1000" into count of individual VLANs. */
function countVlansInRange(rangeStr: string): number {
  const parts = rangeStr.split('-');
  if (parts.length === 2) {
    const start = parseInt(parts[0], 10);
    const end = parseInt(parts[1], 10);
    if (!isNaN(start) && !isNaN(end) && end >= start) return end - start + 1;
  }
  return isNaN(parseInt(rangeStr, 10)) ? 0 : 1;
}

function totalVlanCount(ranges: string[]): number {
  return ranges.reduce((sum, r) => sum + countVlansInRange(r), 0);
}

/** Expand VLAN range strings into individual VLAN numbers. */
function expandRange(rangeStr: string): number[] {
  const parts = rangeStr.split('-');
  if (parts.length === 2) {
    const start = parseInt(parts[0], 10);
    const end = parseInt(parts[1], 10);
    if (!isNaN(start) && !isNaN(end) && end >= start && (end - start) <= 5000) {
      const result: number[] = [];
      for (let i = start; i <= end; i++) result.push(i);
      return result;
    }
  }
  const single = parseInt(rangeStr, 10);
  return isNaN(single) ? [] : [single];
}

export default function FacilityPortsBrowser({ facilityPorts, loading }: FacilityPortsBrowserProps) {
  const [search, setSearch] = useState('');
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [sortBy, setSortBy] = useState<'name' | 'site'>('site');

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    let result = facilityPorts;
    if (q) {
      result = result.filter(
        (fp) =>
          fp.name.toLowerCase().includes(q) ||
          fp.site.toLowerCase().includes(q) ||
          fp.interfaces.some(
            (i) =>
              i.local_name.toLowerCase().includes(q) ||
              i.device_name.toLowerCase().includes(q) ||
              i.vlan_range.some((v) => v.includes(q))
          )
      );
    }
    return [...result].sort((a, b) =>
      sortBy === 'site'
        ? a.site.localeCompare(b.site) || a.name.localeCompare(b.name)
        : a.name.localeCompare(b.name)
    );
  }, [facilityPorts, search, sortBy]);

  const toggleRow = (name: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  if (loading && facilityPorts.length === 0) {
    return <div className="rb-loading">Loading facility ports...</div>;
  }

  if (!loading && facilityPorts.length === 0) {
    return <div className="rb-loading">No facility ports available. Click "Update Resources" to load data.</div>;
  }

  return (
    <div className="rb-root">
      <div className="rb-toolbar">
        <input
          className="rb-search"
          type="text"
          placeholder="Search by name, site, VLAN, or device..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="fp-sort-select"
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as 'name' | 'site')}
        >
          <option value="site">Sort by Site</option>
          <option value="name">Sort by Name</option>
        </select>
        <span className="rb-count">{filtered.length} facility ports</span>
      </div>
      <div className="rb-table-wrap">
        <table className="rb-table">
          <thead>
            <tr>
              <th style={{ width: 20 }}></th>
              <th>Name</th>
              <th>Site</th>
              <th>VLAN Range</th>
              <th>Available</th>
              <th>Local Name</th>
              <th>Device</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((fp) => {
              const expanded = expandedRows.has(fp.name);
              const iface = fp.interfaces[0];
              const vlanCount = iface ? totalVlanCount(iface.vlan_range) : 0;
              const allocCount = iface?.allocated_vlans ? totalVlanCount(iface.allocated_vlans) : 0;
              return (
                <React.Fragment key={fp.name}>
                  <tr
                    className={`rb-row ${expanded ? 'expanded' : ''}`}
                    onClick={() => toggleRow(fp.name)}
                    style={{ cursor: 'pointer' }}
                  >
                    <td className="rb-expand-cell">
                      {expanded ? '\u25BC' : '\u25B6'}
                    </td>
                    <td className="rb-site-name">{fp.name}</td>
                    <td>
                      <span className="fp-site-badge">{fp.site}</span>
                    </td>
                    <td className="fp-vlan-cell">
                      {iface ? iface.vlan_range.join(', ') || '\u2014' : '\u2014'}
                    </td>
                    <td className="fp-vlan-count">
                      {allocCount > 0 ? (
                        <span>
                          <span className="fp-avail-count">{vlanCount - allocCount}</span>
                          <span className="fp-alloc-count"> / {vlanCount}</span>
                        </span>
                      ) : (
                        <span className="fp-avail-count">{vlanCount}</span>
                      )}
                    </td>
                    <td className="fp-local-name">
                      {iface?.local_name || '\u2014'}
                    </td>
                    <td className="fp-device-name">
                      {iface?.device_name || '\u2014'}
                    </td>
                  </tr>
                  {expanded && iface && (
                    <tr className="rb-detail-row">
                      <td colSpan={7}>
                        <FacilityPortDetail fp={fp} iface={iface} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Expanded detail view for a facility port showing VLAN grid. */
function FacilityPortDetail({ fp, iface }: { fp: FacilityPortInfo; iface: FacilityPortInfo['interfaces'][0] }) {
  const [vlanFilter, setVlanFilter] = useState('');

  const allVlans = useMemo(() => {
    const vlans: number[] = [];
    for (const r of iface.vlan_range) vlans.push(...expandRange(r));
    return vlans;
  }, [iface.vlan_range]);

  const allocatedSet = useMemo(() => {
    const set = new Set<number>();
    for (const r of (iface.allocated_vlans || [])) {
      for (const v of expandRange(r)) set.add(v);
    }
    return set;
  }, [iface.allocated_vlans]);

  const filteredVlans = vlanFilter
    ? allVlans.filter((v) => String(v).includes(vlanFilter))
    : allVlans;

  const allocCount = allocatedSet.size;
  const availCount = allVlans.length - allocCount;

  return (
    <div className="fp-detail">
      <div className="fp-detail-header">
        <div className="fp-detail-info">
          <div className="fp-detail-row">
            <span className="fp-detail-label">Interface:</span>
            <span className="fp-detail-value">{iface.name}</span>
          </div>
          {iface.device_name && (
            <div className="fp-detail-row">
              <span className="fp-detail-label">Device:</span>
              <span className="fp-detail-value">{iface.device_name}</span>
            </div>
          )}
          {iface.region && (
            <div className="fp-detail-row">
              <span className="fp-detail-label">Region:</span>
              <span className="fp-detail-value">{iface.region}</span>
            </div>
          )}
          <div className="fp-detail-row">
            <span className="fp-detail-label">VLAN Range:</span>
            <span className="fp-detail-value fp-mono">{iface.vlan_range.join(', ')}</span>
          </div>
        </div>
        <div className="fp-detail-stats">
          <div className="fp-stat">
            <span className="fp-stat-value fp-stat-available">{availCount}</span>
            <span className="fp-stat-label">available</span>
          </div>
          {allocCount > 0 && (
            <div className="fp-stat">
              <span className="fp-stat-value fp-stat-allocated">{allocCount}</span>
              <span className="fp-stat-label">allocated</span>
            </div>
          )}
          <div className="fp-stat">
            <span className="fp-stat-value">{allVlans.length}</span>
            <span className="fp-stat-label">total</span>
          </div>
        </div>
      </div>

      {/* VLAN grid */}
      <div className="fp-vlan-section">
        <div className="fp-vlan-toolbar">
          <span className="fp-vlan-section-label">VLANs</span>
          <input
            className="fp-vlan-filter"
            type="text"
            placeholder="Filter VLANs..."
            value={vlanFilter}
            onChange={(e) => setVlanFilter(e.target.value)}
            onClick={(e) => e.stopPropagation()}
          />
          <span className="fp-vlan-showing">{filteredVlans.length} shown</span>
        </div>
        {allVlans.length <= 5000 ? (
          <div className="fp-vlan-grid">
            {filteredVlans.map((v) => {
              const isAllocated = allocatedSet.has(v);
              return (
                <span
                  key={v}
                  className={`fp-vlan-chip ${isAllocated ? 'allocated' : 'available'}`}
                  title={isAllocated ? `VLAN ${v} (allocated)` : `VLAN ${v} (available)`}
                >
                  {v}
                </span>
              );
            })}
          </div>
        ) : (
          <div className="fp-vlan-too-many">
            Range too large to display individually ({allVlans.length} VLANs).
            Use the filter to narrow results.
          </div>
        )}
      </div>
    </div>
  );
}
