'use client';
import React, { useState, useRef, useEffect, useMemo } from 'react';
import { MapContainer, TileLayer, CircleMarker, Polyline, Popup, Tooltip, useMap } from 'react-leaflet';
import type { LatLngBoundsExpression } from 'leaflet';
import type { SliceData, SiteInfo, LinkInfo, SiteMetrics, LinkMetrics, PrometheusResult } from '../types/fabric';
import type { ChameleonSite, ChameleonInstance } from '../types/chameleon';
import DetailPanel from './DetailPanel';
import '../styles/geo.css';

// State colors matching fabvis exactly
const STATE_MARKER_COLORS: Record<string, string> = {
  Active: '#008e7a',
  StableOK: '#008e7a',
  Configuring: '#ff8542',
  Ticketed: '#ff8542',
  ModifyOK: '#ff8542',
  Nascent: '#838385',
  StableError: '#b00020',
  ModifyError: '#b00020',
  Closing: '#616161',
  Dead: '#616161',
};

/**
 * Shift longitudes so that far-east sites (Japan) appear to the LEFT of
 * the US on the map, and EU/UK appear to the RIGHT.
 * Sites with lon > 100 are shifted by -360.
 */
function shiftLon(lon: number): number {
  return lon > 100 ? lon - 360 : lon;
}

// --- Load indicator helpers ---

/** FABRIC brand colors for load levels */
const COLOR_LOW = '#008e7a';    // teal
const COLOR_MEDIUM = '#ff8542'; // orange
const COLOR_HIGH = '#e25241';   // coral
const COLOR_NONE = '#999';      // gray (no data)
const COLOR_LINK_DEFAULT = '#5798bc'; // primary blue

/** Compute site utilization (0-1) from cores_available / cores_capacity */
function getSiteUtilization(site: SiteInfo): number | null {
  if (!site.cores_capacity || site.cores_capacity <= 0) return null;
  return 1 - (site.cores_available / site.cores_capacity);
}

/** Map utilization to a color */
function utilizationColor(util: number | null): string {
  if (util === null) return COLOR_NONE;
  if (util < 0.5) return COLOR_LOW;
  if (util <= 0.8) return COLOR_MEDIUM;
  return COLOR_HIGH;
}

/** Average load1 from SiteMetrics */
function avgLoad1(metrics: SiteMetrics | undefined): number | null {
  if (!metrics || !metrics.node_load1 || metrics.node_load1.length === 0) return null;
  const sum = metrics.node_load1.reduce((acc: number, r: PrometheusResult) => acc + parseFloat(r.value[1] || '0'), 0);
  return sum / metrics.node_load1.length;
}

/** Sum total bits/s for an array of PrometheusResult (picks the highest single value if multiple interfaces) */
function sumBits(results: PrometheusResult[] | undefined): number {
  if (!results || results.length === 0) return 0;
  return results.reduce((acc, r) => acc + Math.abs(parseFloat(r.value[1] || '0')), 0);
}

/** Format bits/s to human-readable */
function formatBps(bits: number): string {
  if (bits >= 1e12) return (bits / 1e12).toFixed(1) + ' Tbps';
  if (bits >= 1e9) return (bits / 1e9).toFixed(1) + ' Gbps';
  if (bits >= 1e6) return (bits / 1e6).toFixed(1) + ' Mbps';
  if (bits >= 1e3) return (bits / 1e3).toFixed(0) + ' Kbps';
  return bits.toFixed(0) + ' bps';
}

/** Get link color and weight by total traffic (in + out bits/s) */
function linkStyle(metrics: LinkMetrics | undefined): { color: string; weight: number } {
  if (!metrics) return { color: COLOR_LINK_DEFAULT, weight: 2 };
  const totalIn = sumBits(metrics.a_to_b_in) + sumBits(metrics.b_to_a_in);
  const totalOut = sumBits(metrics.a_to_b_out) + sumBits(metrics.b_to_a_out);
  const total = totalIn + totalOut;
  if (total > 10e9) return { color: COLOR_HIGH, weight: 6 };
  if (total > 1e9) return { color: COLOR_MEDIUM, weight: 4 };
  return { color: COLOR_LINK_DEFAULT, weight: 2 };
}

/** Legend overlay component rendered inside the MapContainer */
function MapLegend() {
  return (
    <div className="geo-legend">
      <div className="geo-legend-section">
        <span className="geo-legend-title">Site Load</span>
        <div className="geo-legend-item">
          <span className="geo-legend-dot" style={{ background: COLOR_LOW }} />
          <span>Low (&lt;50%)</span>
        </div>
        <div className="geo-legend-item">
          <span className="geo-legend-dot" style={{ background: COLOR_MEDIUM }} />
          <span>Medium (50-80%)</span>
        </div>
        <div className="geo-legend-item">
          <span className="geo-legend-dot" style={{ background: COLOR_HIGH }} />
          <span>High (&gt;80%)</span>
        </div>
        <div className="geo-legend-item">
          <span className="geo-legend-dot" style={{ background: COLOR_NONE }} />
          <span>No data</span>
        </div>
      </div>
      <div className="geo-legend-section">
        <span className="geo-legend-title">Link Traffic</span>
        <div className="geo-legend-item">
          <span className="geo-legend-line" style={{ background: COLOR_LINK_DEFAULT, height: 2 }} />
          <span>Low (&lt;1G)</span>
        </div>
        <div className="geo-legend-item">
          <span className="geo-legend-line" style={{ background: COLOR_MEDIUM, height: 3 }} />
          <span>Medium (1-10G)</span>
        </div>
        <div className="geo-legend-item">
          <span className="geo-legend-line" style={{ background: COLOR_HIGH, height: 5 }} />
          <span>High (&gt;10G)</span>
        </div>
      </div>
    </div>
  );
}

/** Fit the map to show all sites with padding. */
function FitBounds({ sites }: { sites: SiteInfo[] }) {
  const map = useMap();
  const fitted = useRef(false);

  useEffect(() => {
    if (sites.length === 0 || fitted.current) return;
    const lats = sites.map((s) => s.lat);
    const lons = sites.map((s) => shiftLon(s.lon));
    const bounds: LatLngBoundsExpression = [
      [Math.min(...lats) - 3, Math.min(...lons) - 5],
      [Math.max(...lats) + 3, Math.max(...lons) + 5],
    ];
    map.fitBounds(bounds, { padding: [20, 20], maxZoom: 5 });
    fitted.current = true;
  }, [sites, map]);

  return null;
}

interface GeoViewProps {
  sliceData: SliceData | null;
  selectedElement: Record<string, string> | null;
  onNodeClick: (data: Record<string, string>) => void;
  sites: SiteInfo[];
  links: LinkInfo[];
  linksLoading?: boolean;
  siteMetricsCache: Record<string, SiteMetrics>;
  linkMetricsCache: Record<string, LinkMetrics>;
  metricsRefreshRate: number;
  onMetricsRefreshRateChange: (rate: number) => void;
  onRefreshMetrics: () => void;
  metricsLoading: boolean;
  collapsibleDetail?: boolean;
  /** Hide the internal DetailPanel entirely (when external panels handle it) */
  hideDetail?: boolean;
  /** Default visibility for infrastructure layers (sites/links). Defaults to true. */
  defaultShowInfra?: boolean;
  /** Hide the infrastructure toggle controls entirely */
  hideInfraToggles?: boolean;
  /** Chameleon Cloud sites to show on the map (orange markers) */
  chameleonSites?: ChameleonSite[];
  /** Chameleon Cloud instances to overlay on map near their site */
  chameleonInstances?: ChameleonInstance[];
}

const TILE_LIGHT = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}';
const TILE_DARK = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
const ATTR_LIGHT = '&copy; Esri';
const ATTR_DARK = '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>';

export default React.memo(function GeoView({ sliceData, selectedElement, onNodeClick, sites, links, linksLoading, siteMetricsCache, linkMetricsCache, metricsRefreshRate, onMetricsRefreshRateChange, onRefreshMetrics, metricsLoading, collapsibleDetail, hideDetail, defaultShowInfra = true, hideInfraToggles, chameleonSites, chameleonInstances }: GeoViewProps) {
  const [showInfraSites, setShowInfraSites] = useState(defaultShowInfra);
  const [showInfraLinks, setShowInfraLinks] = useState(defaultShowInfra);
  const [showSliceNodes, setShowSliceNodes] = useState(true);
  const [showSliceLinks, setShowSliceLinks] = useState(true);
  const [showChameleonSites, setShowChameleonSites] = useState(true);
  const [showChameleonInstances, setShowChameleonInstances] = useState(true);
  const [detailCollapsed, setDetailCollapsed] = useState(false);
  const [mapDark, setMapDark] = useState(() => localStorage.getItem('map-theme') === 'dark');

  const toggleMapDark = () => {
    setMapDark(prev => {
      const next = !prev;
      localStorage.setItem('map-theme', next ? 'dark' : 'light');
      return next;
    });
  };

  // Build site lookup
  const siteLookup = new Map(sites.map((s) => [s.name, s]));

  // Build Chameleon instance-by-site lookup
  const chiInstancesBySite = useMemo(() => {
    if (!chameleonInstances?.length || !chameleonSites?.length) return new Map<string, ChameleonInstance[]>();
    const map = new Map<string, ChameleonInstance[]>();
    for (const inst of chameleonInstances) {
      const list = map.get(inst.site) || [];
      list.push(inst);
      map.set(inst.site, list);
    }
    return map;
  }, [chameleonInstances, chameleonSites]);

  // Group slice nodes by site
  const nodesBySite = new Map<string, NonNullable<typeof sliceData>['nodes']>();
  if (sliceData) {
    for (const node of sliceData.nodes) {
      const list = nodesBySite.get(node.site) ?? [];
      list.push(node);
      nodesBySite.set(node.site, list);
    }
  }

  // Build slice network connections between sites
  const sliceConnections: { from: SiteInfo; to: SiteInfo; netName: string; color: string }[] = [];
  if (sliceData && showSliceLinks) {
    for (const net of sliceData.networks) {
      const nodeSites = new Set<string>();
      for (const iface of net.interfaces) {
        const node = sliceData.nodes.find((n) => n.name === iface.node_name);
        if (node) nodeSites.add(node.site);
      }
      const siteList = [...nodeSites].map((s) => siteLookup.get(s)).filter(Boolean) as SiteInfo[];
      const color = net.layer === 'L3' ? '#008e7a' : '#1f6a8c';
      for (let i = 0; i < siteList.length - 1; i++) {
        sliceConnections.push({ from: siteList[i], to: siteList[i + 1], netName: net.name, color });
      }
    }
  }

  // Build backbone links from API data (with metrics key for styling)
  const infraLinks: { from: SiteInfo; to: SiteInfo; metricsKey: string }[] = [];
  if (showInfraLinks) {
    for (const link of links) {
      const sA = siteLookup.get(link.site_a);
      const sB = siteLookup.get(link.site_b);
      if (sA && sB) infraLinks.push({ from: sA, to: sB, metricsKey: `${link.site_a}-${link.site_b}` });
    }
  }

  return (
    <div className="geo-view" data-help-id="map.view">
      <div className="geo-map-container">
        <div className="geo-controls">
          {!hideInfraToggles && (
            <div className="geo-control-group">
              <span className="geo-group-label">Infrastructure</span>
              <label title="Show/hide FABRIC infrastructure sites on the map">
                <input type="checkbox" checked={showInfraSites} onChange={(e) => setShowInfraSites(e.target.checked)} />
                Sites
              </label>
              <label title="Show/hide backbone network links between sites">
                <input type="checkbox" checked={showInfraLinks} onChange={(e) => setShowInfraLinks(e.target.checked)} />
                Links
                {linksLoading && <span className="geo-loading-indicator"> (loading...)</span>}
              </label>
            </div>
          )}
          {sliceData && (
            <div className="geo-control-group">
              <span className="geo-group-label">Slice</span>
              <label title="Show/hide slice node locations">
                <input type="checkbox" checked={showSliceNodes} onChange={(e) => setShowSliceNodes(e.target.checked)} />
                Nodes
              </label>
              <label title="Show/hide slice network connections">
                <input type="checkbox" checked={showSliceLinks} onChange={(e) => setShowSliceLinks(e.target.checked)} />
                Links
              </label>
            </div>
          )}
          {(chameleonSites?.length || chameleonInstances?.length) ? (
            <div className="geo-control-group">
              <span className="geo-group-label">Chameleon</span>
              <label title="Show/hide Chameleon Cloud sites">
                <input type="checkbox" checked={showChameleonSites} onChange={(e) => setShowChameleonSites(e.target.checked)} />
                Sites
              </label>
              <label title="Show/hide Chameleon Cloud instances">
                <input type="checkbox" checked={showChameleonInstances} onChange={(e) => setShowChameleonInstances(e.target.checked)} />
                Instances
              </label>
            </div>
          ) : null}
          <button className={`geo-theme-toggle ${mapDark ? 'dark' : 'light'}`} onClick={toggleMapDark} title={mapDark ? 'Switch to light map' : 'Switch to dark map'}>
            {mapDark ? '☀' : '☾'}
          </button>
        </div>
        <MapContainer
          center={[38, -95]}
          zoom={3}
          style={{ width: '100%', height: '100%' }}
          scrollWheelZoom={true}
          worldCopyJump={false}
        >
          <TileLayer
            key={mapDark ? 'dark' : 'light'}
            attribution={mapDark ? ATTR_DARK : ATTR_LIGHT}
            url={mapDark ? TILE_DARK : TILE_LIGHT}
          />
          <FitBounds sites={sites} />

          {/* Infrastructure backbone links (colored/weighted by traffic) */}
          {infraLinks.map((link, i) => {
            const lm = linkMetricsCache[link.metricsKey];
            const ls = linkStyle(lm);
            return (
              <Polyline
                key={`infra-${i}`}
                positions={[
                  [link.from.lat, shiftLon(link.from.lon)],
                  [link.to.lat, shiftLon(link.to.lon)],
                ]}
                pathOptions={{
                  color: ls.color,
                  weight: ls.weight,
                  opacity: 0.5,
                }}
                eventHandlers={{
                  click: () => onNodeClick({
                    element_type: 'infra_link',
                    name: `${link.from.name} — ${link.to.name}`,
                    site_a: link.from.name,
                    site_b: link.to.name,
                  }),
                }}
              >
                <Tooltip sticky>
                  <span style={{ fontSize: 12 }}>
                    <strong>{link.from.name} — {link.to.name}</strong>
                    {lm ? (
                      <>
                        <br />In: {formatBps(sumBits(lm.a_to_b_in) + sumBits(lm.b_to_a_in))}
                        <br />Out: {formatBps(sumBits(lm.a_to_b_out) + sumBits(lm.b_to_a_out))}
                      </>
                    ) : (
                      <><br />No traffic data</>
                    )}
                  </span>
                </Tooltip>
              </Polyline>
            );
          })}

          {/* Site markers (colored by utilization) */}
          {showInfraSites && sites.map((site) => {
            const util = getSiteUtilization(site);
            const fillColor = utilizationColor(util);
            const metrics = siteMetricsCache[site.name];
            const load = avgLoad1(metrics);
            const inBits = metrics ? sumBits(metrics.dataplaneInBits) : 0;
            const outBits = metrics ? sumBits(metrics.dataplaneOutBits) : 0;
            const utilPct = util !== null ? Math.round(util * 100) : null;
            return (
              <CircleMarker
                key={site.name}
                center={[site.lat, shiftLon(site.lon)]}
                radius={7}
                pathOptions={{
                  color: '#fff',
                  fillColor,
                  fillOpacity: 0.85,
                  weight: 2,
                }}
                eventHandlers={{
                  click: () => onNodeClick({
                    element_type: 'site',
                    name: site.name,
                    state: site.state,
                    hosts: String(site.hosts),
                    lat: String(site.lat),
                    lon: String(site.lon),
                    cores_available: String(site.cores_available ?? 0),
                    cores_capacity: String(site.cores_capacity ?? 0),
                    ram_available: String(site.ram_available ?? 0),
                    ram_capacity: String(site.ram_capacity ?? 0),
                    disk_available: String(site.disk_available ?? 0),
                    disk_capacity: String(site.disk_capacity ?? 0),
                  }),
                }}
              >
                <Tooltip sticky>
                  <span style={{ fontSize: 12 }}>
                    <strong>{site.name}</strong>
                    <br />Utilization: {utilPct !== null ? `${utilPct}%` : 'N/A'} ({site.cores_available}/{site.cores_capacity} cores free)
                    {load !== null && <><br />CPU Load: {load.toFixed(1)}</>}
                    {metrics && (inBits > 0 || outBits > 0) && (
                      <><br />Traffic: {formatBps(inBits)} in / {formatBps(outBits)} out</>
                    )}
                  </span>
                </Tooltip>
                <Popup>
                  <div className="site-popup">
                    <h3>{site.name}</h3>
                    <p>State: {site.state}</p>
                    <p>Hosts: {site.hosts}</p>
                    <p>Cores: {site.cores_available}/{site.cores_capacity} available</p>
                    {utilPct !== null && <p>Utilization: {utilPct}%</p>}
                    {load !== null && <p>CPU Load (1m avg): {load.toFixed(2)}</p>}
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}

          {/* Chameleon site markers (orange) */}
          {showChameleonSites && chameleonSites && chameleonSites.filter(s => s.configured).map((site) => (
            <CircleMarker
              key={`chi-${site.name}`}
              center={[site.location.lat, shiftLon(site.location.lon)]}
              radius={7}
              pathOptions={{
                color: '#ff8542',
                fillColor: '#ff8542',
                fillOpacity: 0.7,
                weight: 2,
              }}
              eventHandlers={{
                click: () => onNodeClick({
                  element_type: 'chameleon_site',
                  name: site.name,
                  provider: 'Chameleon Cloud',
                  city: site.location.city || '',
                }),
              }}
            >
              <Popup>
                <div className="site-popup">
                  <h3>{site.name}</h3>
                  <p>Provider: Chameleon Cloud</p>
                  <p>{site.location.city || ''}</p>
                </div>
              </Popup>
            </CircleMarker>
          ))}

          {/* Chameleon instance markers (offset from site position) */}
          {showChameleonInstances && chameleonInstances && chameleonSites?.filter(s => s.configured).map(site => {
            const siteInsts = chiInstancesBySite.get(site.name) || [];
            return siteInsts.map((inst, idx) => (
              <CircleMarker
                key={`chi-inst-${inst.id}`}
                center={[site.location.lat + (idx + 1) * 0.25, shiftLon(site.location.lon) + (idx + 1) * 0.25]}
                radius={8}
                pathOptions={{
                  color: inst.status === 'ACTIVE' ? '#39B54A' : inst.status === 'ERROR' ? '#b00020' : '#ff8542',
                  fillColor: inst.status === 'ACTIVE' ? '#39B54A' : inst.status === 'ERROR' ? '#b00020' : '#ff8542',
                  fillOpacity: 0.85,
                  weight: 2,
                }}
                eventHandlers={{
                  click: () => onNodeClick({
                    element_type: 'chameleon_instance',
                    name: inst.name,
                    site: inst.site,
                    status: inst.status,
                    ip: (inst.ip_addresses || []).join(', '),
                    floating_ip: inst.floating_ip || '',
                    instance_id: inst.id,
                    image: inst.image || '',
                    created: inst.created || '',
                  }),
                }}
              >
                <Tooltip direction="top" offset={[0, -8]}>
                  <span style={{ fontSize: 12 }}>
                    <strong>{inst.name}</strong> ({inst.status})
                    {inst.floating_ip && <><br />IP: {inst.floating_ip}</>}
                  </span>
                </Tooltip>
              </CircleMarker>
            ));
          })}

          {/* Slice node markers (larger, colored by state) */}
          {sliceData && showSliceNodes && [...nodesBySite.entries()].map(([siteName, nodes]) => {
            const site = siteLookup.get(siteName);
            if (!site) return null;
            return nodes.map((node, idx) => (
              <CircleMarker
                key={`${siteName}-${node.name}`}
                center={[site.lat + idx * 0.3, shiftLon(site.lon) + idx * 0.3]}
                radius={10}
                pathOptions={{
                  color: STATE_MARKER_COLORS[node.reservation_state] ?? '#838385',
                  fillColor: STATE_MARKER_COLORS[node.reservation_state] ?? '#838385',
                  fillOpacity: 0.8,
                  weight: 3,
                }}
                eventHandlers={{
                  click: () => onNodeClick({
                    element_type: 'node',
                    name: node.name,
                    site: node.site,
                    cores: String(node.cores),
                    ram: String(node.ram),
                    disk: String(node.disk),
                    state: node.reservation_state,
                    image: node.image,
                    management_ip: node.management_ip,
                    username: node.username,
                    host: node.host,
                    state_bg: '',
                    state_color: '',
                  }),
                }}
              >
                <Popup>
                  <div className="site-popup">
                    <h3>{node.name}</h3>
                    <p>Site: {siteName}</p>
                    <p>State: {node.reservation_state}</p>
                    <p>{node.cores}c / {node.ram}G / {node.disk}G</p>
                  </div>
                </Popup>
              </CircleMarker>
            ));
          })}

          {/* Slice network connections between sites */}
          {sliceConnections.map((conn, i) => (
            <Polyline
              key={`slice-conn-${i}`}
              positions={[
                [conn.from.lat, shiftLon(conn.from.lon)],
                [conn.to.lat, shiftLon(conn.to.lon)],
              ]}
              pathOptions={{
                color: conn.color,
                weight: 3,
                opacity: 0.7,
                dashArray: conn.color === '#008e7a' ? '10 5' : undefined,
              }}
              eventHandlers={{
                click: () => onNodeClick({
                  element_type: 'network',
                  name: conn.netName,
                  type: '',
                  layer: conn.color === '#008e7a' ? 'L3' : 'L2',
                  subnet: '',
                  gateway: '',
                }),
              }}
            >
              <Popup>{conn.netName}</Popup>
            </Polyline>
          ))}
        </MapContainer>
        {showInfraSites && <MapLegend />}
      </div>

      {/* Detail panel on the right (hidden when external panels handle it) */}
      {!hideDetail && (
        collapsibleDetail && detailCollapsed ? (
          <button
            className="geo-detail-expand-btn"
            onClick={() => setDetailCollapsed(false)}
            title="Show details panel"
          >
            {'\u2039'}
          </button>
        ) : (
          <DetailPanel
            sliceData={sliceData}
            selectedElement={selectedElement}
            siteMetricsCache={siteMetricsCache}
            linkMetricsCache={linkMetricsCache}
            metricsRefreshRate={metricsRefreshRate}
            onMetricsRefreshRateChange={onMetricsRefreshRateChange}
            onRefreshMetrics={onRefreshMetrics}
            metricsLoading={metricsLoading}
            onCollapse={collapsibleDetail ? () => setDetailCollapsed(true) : undefined}
          />
        )
      )}
    </div>
  );
});
