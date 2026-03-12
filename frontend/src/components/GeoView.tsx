'use client';
import React, { useState, useRef, useEffect } from 'react';
import { MapContainer, TileLayer, CircleMarker, Polyline, Popup, useMap } from 'react-leaflet';
import type { LatLngBoundsExpression } from 'leaflet';
import type { SliceData, SiteInfo, LinkInfo, SiteMetrics, LinkMetrics } from '../types/fabric';
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
}

const TILE_LIGHT = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}';
const TILE_DARK = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
const ATTR_LIGHT = '&copy; Esri';
const ATTR_DARK = '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>';

export default React.memo(function GeoView({ sliceData, selectedElement, onNodeClick, sites, links, linksLoading, siteMetricsCache, linkMetricsCache, metricsRefreshRate, onMetricsRefreshRateChange, onRefreshMetrics, metricsLoading, collapsibleDetail, hideDetail, defaultShowInfra = true, hideInfraToggles }: GeoViewProps) {
  const [showInfraSites, setShowInfraSites] = useState(defaultShowInfra);
  const [showInfraLinks, setShowInfraLinks] = useState(defaultShowInfra);
  const [showSliceNodes, setShowSliceNodes] = useState(true);
  const [showSliceLinks, setShowSliceLinks] = useState(true);
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

  // Build backbone links from API data
  const infraLinks: { from: SiteInfo; to: SiteInfo }[] = [];
  if (showInfraLinks) {
    for (const link of links) {
      const sA = siteLookup.get(link.site_a);
      const sB = siteLookup.get(link.site_b);
      if (sA && sB) infraLinks.push({ from: sA, to: sB });
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

          {/* Infrastructure backbone links */}
          {infraLinks.map((link, i) => (
            <Polyline
              key={`infra-${i}`}
              positions={[
                [link.from.lat, shiftLon(link.from.lon)],
                [link.to.lat, shiftLon(link.to.lon)],
              ]}
              pathOptions={{
                color: '#5798bc',
                weight: 2,
                opacity: 0.4,
              }}
              eventHandlers={{
                click: () => onNodeClick({
                  element_type: 'infra_link',
                  name: `${link.from.name} — ${link.to.name}`,
                  site_a: link.from.name,
                  site_b: link.to.name,
                }),
              }}
            />
          ))}

          {/* Site markers */}
          {showInfraSites && sites.map((site) => (
            <CircleMarker
              key={site.name}
              center={[site.lat, shiftLon(site.lon)]}
              radius={6}
              pathOptions={{
                color: '#5798bc',
                fillColor: '#5798bc',
                fillOpacity: 0.6,
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
              <Popup>
                <div className="site-popup">
                  <h3>{site.name}</h3>
                  <p>State: {site.state}</p>
                  <p>Hosts: {site.hosts}</p>
                </div>
              </Popup>
            </CircleMarker>
          ))}

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
