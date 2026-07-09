'use client';
import { MapContainer, TileLayer, CircleMarker, Tooltip } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

// Known SPHERE enclave coordinates (mirrors backend SPHERE_SITE_LOCATIONS).
const ENCLAVES: { name: string; lat: number; lon: number; city: string }[] = [
  { name: 'USC-ISI', lat: 33.9931, lon: -118.4517, city: 'Marina del Rey, CA' },
  { name: 'Northeastern', lat: 42.3398, lon: -71.0892, city: 'Boston, MA' },
  { name: 'Utah', lat: 40.7649, lon: -111.8421, city: 'Salt Lake City, UT' },
];

interface SphereMapProps {
  inventory: { facilities: any[]; resources: any[] } | null;
  usedFacilities: Set<string>;
  dark: boolean;
}

/**
 * Geographic view of the SPHERE testbed. SPHERE facilities are logical (no
 * per-facility GPS in the API), so we plot the known SPHERE enclaves and list
 * the facilities/resources alongside, highlighting any facility used by the
 * selected realization.
 */
export default function SphereMap({ inventory, usedFacilities, dark }: SphereMapProps) {
  const facilities = inventory?.facilities || [];
  const resources = inventory?.resources || [];
  const countFor = (fac: string) => resources.filter(r => (r?.resource || r || {}).facility === fac).length;

  return (
    <div style={{ display: 'flex', height: '100%', minHeight: 0 }}>
      <div style={{ flex: 1, minHeight: 0 }}>
        <MapContainer center={[39.5, -98.35]} zoom={4} style={{ height: '100%', width: '100%' }} scrollWheelZoom>
          <TileLayer
            attribution='&copy; OpenStreetMap'
            url={dark
              ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
              : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'}
          />
          {ENCLAVES.map(e => (
            <CircleMarker key={e.name} center={[e.lat, e.lon]} radius={11}
              pathOptions={{ color: '#0a1f44', fillColor: '#23467f', fillOpacity: 0.85, weight: 2 }}>
              <Tooltip>
                <div style={{ fontWeight: 700 }}>{e.name}</div>
                <div style={{ fontSize: 11 }}>{e.city}</div>
              </Tooltip>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>
      <div style={{ width: 240, borderLeft: '1px solid var(--fabric-border)', overflow: 'auto', padding: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', opacity: 0.7, marginBottom: 6 }}>
          Facilities ({facilities.length})
        </div>
        {facilities.length === 0 && <div style={{ fontSize: 12, opacity: 0.6 }}>No facility data.</div>}
        {facilities.map((f: any) => {
          const used = usedFacilities.has(f.name);
          return (
            <div key={f.name} style={{
              padding: '6px 8px', marginBottom: 5, borderRadius: 5, fontSize: 12,
              border: '1px solid var(--fabric-border)',
              background: used ? 'rgba(0,142,122,0.12)' : 'transparent',
            }}>
              <div style={{ fontWeight: 600 }}>
                {f.name}{used && <span style={{ color: '#008e7a', fontSize: 10 }}> ● in this realization</span>}
              </div>
              <div style={{ fontSize: 10, opacity: 0.7, fontFamily: 'monospace', wordBreak: 'break-all' }}>{f.address || ''}</div>
              <div style={{ fontSize: 10, opacity: 0.7 }}>{countFor(f.name)} resources</div>
            </div>
          );
        })}
        <div style={{ fontSize: 10, opacity: 0.55, marginTop: 8 }}>
          Markers show SPHERE enclaves; individual facilities are not geo-tagged in the API.
        </div>
      </div>
    </div>
  );
}
