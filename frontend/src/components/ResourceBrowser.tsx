'use client';
import React, { useState, useMemo } from 'react';
import type { SiteInfo, SiteDetail, HostInfo, ComponentResource } from '../types/fabric';
import * as api from '../api/client';
import '../styles/infrastructure-view.css';

/** Aggregate host data into site-level totals (more accurate than orchestrator site data) */
function aggregateHosts(hostList: HostInfo[]): {
  cores_available: number; cores_capacity: number;
  ram_available: number; ram_capacity: number;
  disk_available: number; disk_capacity: number;
  components: Record<string, { available: number; capacity: number }>;
} {
  let cores_a = 0, cores_c = 0, ram_a = 0, ram_c = 0, disk_a = 0, disk_c = 0;
  const comps: Record<string, { available: number; capacity: number }> = {};
  for (const h of hostList) {
    cores_a += h.cores_available;
    cores_c += h.cores_capacity;
    ram_a += h.ram_available;
    ram_c += h.ram_capacity;
    disk_a += h.disk_available;
    disk_c += h.disk_capacity;
    if (h.components) {
      for (const [k, v] of Object.entries(h.components)) {
        if (!comps[k]) comps[k] = { available: 0, capacity: 0 };
        comps[k].available += v.available;
        comps[k].capacity += v.capacity;
      }
    }
  }
  return { cores_available: cores_a, cores_capacity: cores_c, ram_available: ram_a, ram_capacity: ram_c, disk_available: disk_a, disk_capacity: disk_c, components: comps };
}

interface ResourceBrowserProps {
  sites: SiteInfo[];
}

export default function ResourceBrowser({ sites }: ResourceBrowserProps) {
  const [search, setSearch] = useState('');
  const [expandedSite, setExpandedSite] = useState<string | null>(null);
  const [siteDetail, setSiteDetail] = useState<SiteDetail | null>(null);
  const [hosts, setHosts] = useState<HostInfo[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [expandedHost, setExpandedHost] = useState<string | null>(null);

  const filtered = useMemo(() => {
    if (!search) return sites;
    const q = search.toLowerCase();
    return sites.filter(s => s.name.toLowerCase().includes(q));
  }, [sites, search]);

  // Recompute site-level totals from hosts (orchestrator site data can be inaccurate)
  const hostAgg = useMemo(() => hosts.length > 0 ? aggregateHosts(hosts) : null, [hosts]);

  // Effective site detail: prefer host-aggregated data over orchestrator site data
  const effectiveDetail = useMemo(() => {
    if (!siteDetail) return null;
    if (!hostAgg) return siteDetail;
    // Merge: use host-aggregated resources, keep siteDetail metadata (lat, lon, state, etc.)
    const mergedComponents: Record<string, ComponentResource> = {};
    for (const [k, v] of Object.entries(hostAgg.components)) {
      mergedComponents[k] = { available: v.available, capacity: v.capacity, allocated: v.capacity - v.available };
    }
    // Also include components from siteDetail that might not appear in host data
    for (const [k, v] of Object.entries(siteDetail.components)) {
      if (!mergedComponents[k]) {
        mergedComponents[k] = v;
      }
    }
    return {
      ...siteDetail,
      cores_available: hostAgg.cores_available,
      cores_capacity: hostAgg.cores_capacity,
      cores_allocated: hostAgg.cores_capacity - hostAgg.cores_available,
      ram_available: hostAgg.ram_available,
      ram_capacity: hostAgg.ram_capacity,
      ram_allocated: hostAgg.ram_capacity - hostAgg.ram_available,
      disk_available: hostAgg.disk_available,
      disk_capacity: hostAgg.disk_capacity,
      disk_allocated: hostAgg.disk_capacity - hostAgg.disk_available,
      components: mergedComponents,
    };
  }, [siteDetail, hostAgg]);

  const handleExpandSite = async (siteName: string) => {
    if (expandedSite === siteName) {
      setExpandedSite(null);
      setExpandedHost(null);
      return;
    }
    setExpandedSite(siteName);
    setExpandedHost(null);
    setDetailLoading(true);
    try {
      const [detail, hostList] = await Promise.all([
        api.getSiteDetail(siteName),
        api.listSiteHosts(siteName),
      ]);
      setSiteDetail(detail);
      setHosts(hostList);
    } catch {
      setSiteDetail(null);
      setHosts([]);
    } finally {
      setDetailLoading(false);
    }
  };

  const availColor = (avail: number, cap: number) => {
    if (cap === 0) return 'var(--fabric-text-muted)';
    const pct = avail / cap;
    if (pct > 0.5) return '#2e7d32';
    if (pct > 0.15) return '#f9a825';
    return '#c62828';
  };

  const pctBar = (avail: number, cap: number) => {
    if (cap === 0) return null;
    const pct = Math.round((avail / cap) * 100);
    return (
      <div className="rb-bar">
        <div className="rb-bar-fill" style={{ width: `${pct}%`, background: availColor(avail, cap) }} />
      </div>
    );
  };

  return (
    <div className="rb-root">
      <div className="rb-toolbar">
        <input
          className="rb-search"
          placeholder="Search sites..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="rb-count">{filtered.length} sites</span>
      </div>
      <div className="rb-table-wrap">
        <table className="rb-table">
          <thead>
            <tr>
              <th></th>
              <th>Site</th>
              <th>State</th>
              <th>Hosts</th>
              <th>Cores</th>
              <th>RAM (GB)</th>
              <th>Disk (GB)</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((site) => (
              <React.Fragment key={site.name}>
                <tr className={`rb-row ${expandedSite === site.name ? 'expanded' : ''}`} onClick={() => handleExpandSite(site.name)}>
                  {(() => {
                    // Use host-aggregated data when this site is expanded and hosts are loaded
                    const eff = expandedSite === site.name && hostAgg ? hostAgg : site;
                    return (
                      <>
                        <td className="rb-expand-cell">{expandedSite === site.name ? '\u25BC' : '\u25B6'}</td>
                        <td className="rb-site-name">{site.name}</td>
                        <td><span className={`rb-state rb-state-${site.state.toLowerCase()}`}>{site.state}</span></td>
                        <td>{site.hosts}</td>
                        <td><span style={{ color: availColor(eff.cores_available, eff.cores_capacity) }}>{eff.cores_available}</span> / {eff.cores_capacity}</td>
                        <td><span style={{ color: availColor(eff.ram_available, eff.ram_capacity) }}>{eff.ram_available}</span> / {eff.ram_capacity}</td>
                        <td><span style={{ color: availColor(eff.disk_available, eff.disk_capacity) }}>{eff.disk_available}</span> / {eff.disk_capacity}</td>
                      </>
                    );
                  })()}
                </tr>
                {expandedSite === site.name && (
                  <tr className="rb-detail-row">
                    <td colSpan={7}>
                      {detailLoading ? (
                        <div className="rb-loading">Loading site details...</div>
                      ) : (
                        <div className="rb-site-detail">
                          {/* Site-level resource summary */}
                          <div className="rb-resource-grid">
                            <div className="rb-resource-card">
                              <div className="rb-resource-label">Cores</div>
                              <div className="rb-resource-value" style={{ color: availColor(effectiveDetail?.cores_available ?? 0, effectiveDetail?.cores_capacity ?? 0) }}>
                                {effectiveDetail?.cores_available ?? 0} <span className="rb-resource-cap">/ {effectiveDetail?.cores_capacity ?? 0}</span>
                              </div>
                              {pctBar(effectiveDetail?.cores_available ?? 0, effectiveDetail?.cores_capacity ?? 0)}
                            </div>
                            <div className="rb-resource-card">
                              <div className="rb-resource-label">RAM (GB)</div>
                              <div className="rb-resource-value" style={{ color: availColor(effectiveDetail?.ram_available ?? 0, effectiveDetail?.ram_capacity ?? 0) }}>
                                {effectiveDetail?.ram_available ?? 0} <span className="rb-resource-cap">/ {effectiveDetail?.ram_capacity ?? 0}</span>
                              </div>
                              {pctBar(effectiveDetail?.ram_available ?? 0, effectiveDetail?.ram_capacity ?? 0)}
                            </div>
                            <div className="rb-resource-card">
                              <div className="rb-resource-label">Disk (GB)</div>
                              <div className="rb-resource-value" style={{ color: availColor(effectiveDetail?.disk_available ?? 0, effectiveDetail?.disk_capacity ?? 0) }}>
                                {effectiveDetail?.disk_available ?? 0} <span className="rb-resource-cap">/ {effectiveDetail?.disk_capacity ?? 0}</span>
                              </div>
                              {pctBar(effectiveDetail?.disk_available ?? 0, effectiveDetail?.disk_capacity ?? 0)}
                            </div>
                            {effectiveDetail && Object.entries(effectiveDetail.components).map(([name, c]) => (
                              <div className="rb-resource-card" key={name}>
                                <div className="rb-resource-label">{name}</div>
                                <div className="rb-resource-value" style={{ color: availColor(c.available, c.capacity) }}>
                                  {c.available} <span className="rb-resource-cap">/ {c.capacity}</span>
                                </div>
                                {pctBar(c.available, c.capacity)}
                              </div>
                            ))}
                          </div>

                          {/* Hosts list */}
                          {hosts.length > 0 && (
                            <div className="rb-hosts-section">
                              <div className="rb-hosts-header">Hosts ({hosts.length})</div>
                              <table className="rb-host-table">
                                <thead>
                                  <tr>
                                    <th></th>
                                    <th>Host</th>
                                    <th>Cores</th>
                                    <th>RAM (GB)</th>
                                    <th>Disk (GB)</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {hosts.map((h) => (
                                    <React.Fragment key={h.name}>
                                      <tr
                                        className={`rb-host-row ${expandedHost === h.name ? 'expanded' : ''}`}
                                        onClick={() => setExpandedHost(expandedHost === h.name ? null : h.name)}
                                      >
                                        <td className="rb-expand-cell">{expandedHost === h.name ? '\u25BC' : '\u25B6'}</td>
                                        <td className="rb-host-name">{h.name}</td>
                                        <td><span style={{ color: availColor(h.cores_available, h.cores_capacity) }}>{h.cores_available}</span> / {h.cores_capacity}</td>
                                        <td><span style={{ color: availColor(h.ram_available, h.ram_capacity) }}>{h.ram_available}</span> / {h.ram_capacity}</td>
                                        <td><span style={{ color: availColor(h.disk_available, h.disk_capacity) }}>{h.disk_available}</span> / {h.disk_capacity}</td>
                                      </tr>
                                      {expandedHost === h.name && (
                                        <tr className="rb-host-detail-row">
                                          <td colSpan={5}>
                                            <div className="rb-resource-grid rb-resource-grid-host">
                                              <div className="rb-resource-card">
                                                <div className="rb-resource-label">Cores</div>
                                                <div className="rb-resource-value" style={{ color: availColor(h.cores_available, h.cores_capacity) }}>
                                                  {h.cores_available} <span className="rb-resource-cap">/ {h.cores_capacity}</span>
                                                </div>
                                                {pctBar(h.cores_available, h.cores_capacity)}
                                              </div>
                                              <div className="rb-resource-card">
                                                <div className="rb-resource-label">RAM (GB)</div>
                                                <div className="rb-resource-value" style={{ color: availColor(h.ram_available, h.ram_capacity) }}>
                                                  {h.ram_available} <span className="rb-resource-cap">/ {h.ram_capacity}</span>
                                                </div>
                                                {pctBar(h.ram_available, h.ram_capacity)}
                                              </div>
                                              <div className="rb-resource-card">
                                                <div className="rb-resource-label">Disk (GB)</div>
                                                <div className="rb-resource-value" style={{ color: availColor(h.disk_available, h.disk_capacity) }}>
                                                  {h.disk_available} <span className="rb-resource-cap">/ {h.disk_capacity}</span>
                                                </div>
                                                {pctBar(h.disk_available, h.disk_capacity)}
                                              </div>
                                              {Object.entries(h.components).map(([name, c]) => (
                                                <div className="rb-resource-card" key={name}>
                                                  <div className="rb-resource-label">{name}</div>
                                                  <div className="rb-resource-value" style={{ color: availColor(c.available, c.capacity) }}>
                                                    {c.available} <span className="rb-resource-cap">/ {c.capacity}</span>
                                                  </div>
                                                  {pctBar(c.available, c.capacity)}
                                                </div>
                                              ))}
                                              {Object.keys(h.components).length === 0 && (
                                                <div className="rb-resource-card rb-resource-card-empty">
                                                  <div className="rb-resource-label">Components</div>
                                                  <div className="rb-no-components">None</div>
                                                </div>
                                              )}
                                            </div>
                                          </td>
                                        </tr>
                                      )}
                                    </React.Fragment>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
