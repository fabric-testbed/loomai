'use client';
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import * as api from '../api/client';
import type { SiteInfo, CalendarData, CalendarSiteSlot, CalendarHostSlot, CalendarTimeSlot, NextAvailableResult, AlternativeResult } from '../types/fabric';
import type { SliceSummary } from '../types/fabric';
import '../styles/resource-calendar.css';

const COMPONENT_TYPES = ['GPU', 'FPGA', 'SmartNIC', 'Storage'] as const;
// Keys MUST match the backend calendar response (hyphen-based resource names from FABRIC orchestrator)
const COMPONENT_MODELS: Record<string, string[]> = {
  GPU: ['GPU-RTX6000', 'GPU-Tesla T4', 'GPU-A30', 'GPU-A40'],
  FPGA: ['FPGA-Xilinx-U280'],
  SmartNIC: ['SmartNIC-ConnectX-5', 'SmartNIC-ConnectX-6', 'SmartNIC-ConnectX-7'],
  Storage: ['NVME-P4510'],
};
// Map backend resource key -> display label for the finder dropdown
const COMPONENT_DISPLAY: Record<string, string> = {
  'GPU-RTX6000': 'GPU RTX6000',
  'GPU-Tesla T4': 'GPU Tesla T4',
  'GPU-A30': 'GPU A30',
  'GPU-A40': 'GPU A40',
  'FPGA-Xilinx-U280': 'FPGA Xilinx U280',
  'SmartNIC-ConnectX-5': 'SmartNIC ConnectX-5',
  'SmartNIC-ConnectX-6': 'SmartNIC ConnectX-6',
  'SmartNIC-ConnectX-7': 'SmartNIC ConnectX-7',
  'NVME-P4510': 'NVMe P4510',
};
// Map backend resource key -> FABlib component model name (for finder API calls)
const COMPONENT_TO_FABLIB: Record<string, string> = {
  'GPU-RTX6000': 'GPU_RTX6000',
  'GPU-Tesla T4': 'GPU_TeslaT4',
  'GPU-A30': 'GPU_A30',
  'GPU-A40': 'GPU_A40',
  'FPGA-Xilinx-U280': 'FPGA_Xilinx_U280',
  'SmartNIC-ConnectX-5': 'NIC_ConnectX_5',
  'SmartNIC-ConnectX-6': 'NIC_ConnectX_6',
  'SmartNIC-ConnectX-7': 'NIC_ConnectX_7',
  'NVME-P4510': 'NVME_P4510',
};
const INTERVAL_OPTIONS: { value: 'hour' | 'day' | 'week'; label: string }[] = [
  { value: 'hour', label: 'Hour' },
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
];

interface ResourceCalendarProps {
  sites: SiteInfo[];
  slices?: SliceSummary[];
}

function formatSlotLabel(iso: string, interval: string): string {
  const d = new Date(iso);
  if (interval === 'hour') {
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  }
  if (interval === 'week') {
    return 'Wk ' + d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

/** Utilization 0-1 (0 = all free, 1 = fully used) */
function coreUtil(site: CalendarSiteSlot | CalendarHostSlot): number {
  if (!site.cores_capacity || site.cores_capacity <= 0) return 0;
  return Math.max(0, Math.min(1, 1 - site.cores_available / site.cores_capacity));
}

/** Utilization for a specific component type across all matching models */
function componentUtil(slot: CalendarSiteSlot | CalendarHostSlot, componentType: string): number {
  const models = COMPONENT_MODELS[componentType] || [];
  let totalCap = 0, totalAvail = 0;
  for (const m of models) {
    const c = slot.components?.[m];
    if (c && c.capacity > 0) {
      totalCap += c.capacity;
      totalAvail += c.available;
    }
  }
  if (totalCap === 0) return 0;
  return Math.max(0, Math.min(1, 1 - totalAvail / totalCap));
}

/** Check if a slot has any capacity for a given component type */
function hasComponentType(slot: CalendarSiteSlot | CalendarHostSlot, componentType: string): boolean {
  const models = COMPONENT_MODELS[componentType] || [];
  return models.some(m => {
    const c = slot.components?.[m];
    return c && c.capacity > 0;
  });
}

/** Utilization for a single specific component model key */
function modelUtil(slot: CalendarSiteSlot | CalendarHostSlot, modelKey: string): number {
  const c = slot.components?.[modelKey];
  if (!c || c.capacity <= 0) return 0;
  return Math.max(0, Math.min(1, 1 - c.available / c.capacity));
}

/** Check if a slot has capacity for a specific model key */
function hasModel(slot: CalendarSiteSlot | CalendarHostSlot, modelKey: string): boolean {
  const c = slot.components?.[modelKey];
  return !!(c && c.capacity > 0);
}

/** Check if a row passes all active filters (any slot in the row must pass) */
function passesFilters(
  rowSlots: (CalendarSiteSlot | CalendarHostSlot)[],
  ft: { types: Set<string>; model: string; cores: number | ''; ram: number | ''; disk: number | '' },
): boolean {
  // Component filter: at least one slot must have the component
  if (ft.model) {
    if (!rowSlots.some(s => hasModel(s, ft.model))) return false;
  } else if (ft.types.size > 0) {
    // Must have ALL selected types (intersection — row must have each selected type in at least one slot)
    for (const t of ft.types) {
      if (!rowSlots.some(s => hasComponentType(s, t))) return false;
    }
  }
  // Resource filters: at least one slot must meet minimums
  if (ft.cores || ft.ram || ft.disk) {
    const meetsResource = rowSlots.some(s => {
      if (ft.cores && s.cores_available < ft.cores) return false;
      if (ft.ram && s.ram_available < ft.ram) return false;
      if (ft.disk && s.disk_available < ft.disk) return false;
      return true;
    });
    if (!meetsResource) return false;
  }
  return true;
}

/** Format component summary for tooltips — shows each model with capacity */
function componentTooltip(slot: CalendarSiteSlot | CalendarHostSlot): string {
  if (!slot.components) return '';
  const parts: string[] = [];
  // Show all components that have capacity, grouped by type
  for (const [type, models] of Object.entries(COMPONENT_MODELS)) {
    const modelParts: string[] = [];
    for (const m of models) {
      const c = slot.components[m];
      if (c && c.capacity > 0) {
        const label = COMPONENT_DISPLAY[m] || m;
        modelParts.push(`  ${label}: ${c.available}/${c.capacity} free`);
      }
    }
    if (modelParts.length > 0) {
      parts.push(type + ':');
      parts.push(...modelParts);
    }
  }
  // Also show any unknown component keys from the backend
  const knownKeys = new Set(Object.values(COMPONENT_MODELS).flat());
  for (const [key, val] of Object.entries(slot.components)) {
    if (!knownKeys.has(key) && val && val.capacity > 0) {
      parts.push(`${key}: ${val.available}/${val.capacity} free`);
    }
  }
  return parts.length > 0 ? '\n' + parts.join('\n') : '';
}

/** Extract site prefix from a host name (e.g., "renc-w1.fabric-testbed.net" -> "RENC") */
function siteFromHost(hostName: string): string {
  const prefix = hostName.split('-')[0] || hostName;
  return prefix.toUpperCase();
}

/** Color for utilization level — FABRIC brand color scheme */
function utilColor(u: number): string {
  if (u < 0.50) return 'var(--fabric-success, #008e7a)';    // Green (FABRIC teal): <50%
  if (u < 0.75) return 'var(--fabric-warning, #ff8542)';    // Yellow/Orange (FABRIC warning): 50-75%
  if (u < 0.90) return 'var(--cal-util-high, #e07020)';     // Deep orange: 75-90%
  return 'var(--fabric-danger, #b00020)';                    // Red (FABRIC danger): 90-100%
}

export default function ResourceCalendar({ sites, slices = [] }: ResourceCalendarProps) {
  const [calendarData, setCalendarData] = useState<CalendarData | null>(null);
  const [calLoading, setCalLoading] = useState(false);
  const [calError, setCalError] = useState('');
  const [calDays, setCalDays] = useState(14);
  const [calInterval, setCalInterval] = useState<'hour' | 'day' | 'week'>('day');
  const [showMode, setShowMode] = useState<'sites' | 'hosts'>('sites');
  const [collapsedSites, setCollapsedSites] = useState<Set<string>>(new Set());

  // Heatmap filters
  const [filterTypes, setFilterTypes] = useState<Set<string>>(new Set());  // multi-select component types
  const [filterModel, setFilterModel] = useState('');      // specific model key: '' | 'GPU-RTX6000' | ...
  const [filterCores, setFilterCores] = useState<number | ''>('');
  const [filterRam, setFilterRam] = useState<number | ''>('');
  const [filterDisk, setFilterDisk] = useState<number | ''>('');
  const [filterOpen, setFilterOpen] = useState(false);
  const [colorBy, setColorBy] = useState<'cores' | 'ram' | 'disk' | string>('cores'); // heatmap color metric

  // Finder state
  const [finderOpen, setFinderOpen] = useState(false);
  const [fCores, setFCores] = useState<number | ''>('');
  const [fRam, setFRam] = useState<number | ''>('');
  const [fDisk, setFDisk] = useState<number | ''>('');
  const [fGpu, setFGpu] = useState('None');
  const [fSite, setFSite] = useState('');
  const [finderLoading, setFinderLoading] = useState(false);
  const [nextResult, setNextResult] = useState<NextAvailableResult | null>(null);
  const [altResult, setAltResult] = useState<AlternativeResult | null>(null);

  // Tooltip
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);

  // Reservation scheduling state
  const [schedOpen, setSchedOpen] = useState(false);
  const [schedSlice, setSchedSlice] = useState('');
  const [schedTime, setSchedTime] = useState('');
  const [schedDuration, setSchedDuration] = useState(24);
  const [schedAutoSubmit, setSchedAutoSubmit] = useState(true);
  const [schedLoading, setSchedLoading] = useState(false);
  const [reservations, setReservations] = useState<api.Reservation[]>([]);

  // Fetch calendar data — always fetch 'all' so we can recompute site totals from hosts
  const loadCalendar = useCallback(async () => {
    setCalLoading(true);
    setCalError('');
    try {
      const data = await api.getScheduleCalendar({
        days: calDays,
        interval: calInterval,
        show: 'all',
      });
      setCalendarData(data);
    } catch (err: unknown) {
      setCalError(err instanceof Error ? err.message : 'Failed to load calendar');
    } finally {
      setCalLoading(false);
    }
  }, [calDays, calInterval]);

  useEffect(() => { loadCalendar(); }, [loadCalendar]);

  // Load reservations
  const loadReservations = useCallback(async () => {
    try {
      const data = await api.listReservations();
      setReservations(data);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadReservations(); }, [loadReservations]);

  const handleSchedule = useCallback(async () => {
    if (!schedSlice || !schedTime) return;
    setSchedLoading(true);
    try {
      await api.createReservation({
        slice_name: schedSlice,
        scheduled_time: new Date(schedTime).toISOString(),
        duration_hours: schedDuration,
        auto_submit: schedAutoSubmit,
      });
      setSchedSlice('');
      setSchedTime('');
      await loadReservations();
    } catch (err: unknown) {
      setCalError(err instanceof Error ? err.message : 'Failed to create reservation');
    } finally {
      setSchedLoading(false);
    }
  }, [schedSlice, schedTime, schedDuration, schedAutoSubmit, loadReservations]);

  const handleCancelReservation = useCallback(async (id: string) => {
    try {
      await api.deleteReservation(id);
      await loadReservations();
    } catch { /* ignore */ }
  }, [loadReservations]);

  // Finder search
  const handleFind = useCallback(async () => {
    setFinderLoading(true);
    setNextResult(null);
    setAltResult(null);
    try {
      const params: { cores?: number; ram?: number; disk?: number; gpu?: string; site?: string } = {};
      if (fCores) params.cores = fCores;
      if (fRam) params.ram = fRam;
      if (fDisk) params.disk = fDisk;
      if (fGpu !== 'None') params.gpu = COMPONENT_TO_FABLIB[fGpu] || fGpu;
      if (fSite) params.site = fSite;
      const result = await api.findNextAvailable(params);
      setNextResult(result);

      if (fSite && !result.available_now.some(a => a.site === fSite)) {
        const altParams: { cores?: number; ram?: number; disk?: number; gpu?: string; preferred_site: string } = {
          preferred_site: fSite,
        };
        if (fCores) altParams.cores = fCores;
        if (fRam) altParams.ram = fRam;
        if (fDisk) altParams.disk = fDisk;
        if (fGpu !== 'None') altParams.gpu = COMPONENT_TO_FABLIB[fGpu] || fGpu;
        try {
          const alt = await api.getAlternatives(altParams);
          setAltResult(alt);
        } catch { /* ignore alternatives error */ }
      }
    } catch (err: unknown) {
      setNextResult({ available_now: [], available_soon: [], not_available: [{ site: '*', reason: err instanceof Error ? err.message : 'Search failed' }] });
    } finally {
      setFinderLoading(false);
    }
  }, [fCores, fRam, fDisk, fGpu, fSite]);

  // Build a per-row, per-slot matrix from calendar data (supports both sites and hosts)
  type RowSlot = CalendarSiteSlot | CalendarHostSlot;
  interface RowGroup {
    site: string;        // site name (grouping key)
    rows: { name: string; slots: RowSlot[] }[];
    isGroup: boolean;    // true when showMode === 'hosts' (collapsible)
  }
  const hasAnyFilter = !!(filterTypes.size || filterModel || filterCores || filterRam || filterDisk);
  const ft = { types: filterTypes, model: filterModel, cores: filterCores, ram: filterRam, disk: filterDisk };

  const { groups, slots, totalRows } = useMemo(() => {
    const empty = { groups: [] as RowGroup[], slots: [] as CalendarTimeSlot[], totalRows: 0 };
    if (!calendarData || !calendarData.data.length) return empty;

    const slots = calendarData.data;
    const emptySlot: RowSlot = { name: '', cores_available: 0, cores_capacity: 0, ram_available: 0, ram_capacity: 0, disk_available: 0, disk_capacity: 0, components: {} };

    if (showMode === 'hosts') {
      // Group hosts by site prefix
      const hostSet = new Set<string>();
      for (const slot of slots) {
        for (const h of slot.hosts || []) hostSet.add(h.name);
      }
      const allHosts = Array.from(hostSet).sort();

      // Build host -> slots map
      const hostSlotMap = new Map<string, RowSlot[]>();
      for (const hName of allHosts) {
        const row: RowSlot[] = [];
        for (const slot of slots) {
          const found = (slot.hosts || []).find(h => h.name === hName);
          row.push(found || { ...emptySlot, name: hName });
        }
        hostSlotMap.set(hName, row);
      }

      // Group by site
      const siteMap = new Map<string, { name: string; slots: RowSlot[] }[]>();
      for (const hName of allHosts) {
        const site = siteFromHost(hName);
        if (!siteMap.has(site)) siteMap.set(site, []);
        siteMap.get(site)!.push({ name: hName, slots: hostSlotMap.get(hName)! });
      }

      const groups: RowGroup[] = Array.from(siteMap.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([site, rows]) => ({ site, rows, isGroup: true }));

      // Apply filters
      if (hasAnyFilter) {
        for (const g of groups) {
          g.rows = g.rows.filter(r => passesFilters(r.slots, ft));
        }
      }
      const filtered = groups.filter(g => g.rows.length > 0);
      const totalRows = filtered.reduce((sum, g) => sum + g.rows.length + 1, 0); // +1 for header
      return { groups: filtered, slots, totalRows };
    } else {
      // Site mode — recompute site totals from host data when available
      // (the orchestrator site-level aggregates can be inaccurate)
      const nameSet = new Set<string>();
      for (const slot of slots) {
        for (const s of slot.sites || []) nameSet.add(s.name);
      }
      const siteNames = Array.from(nameSet).sort();

      // Build a per-site, per-slot lookup from host data for recomputation
      const hasHosts = slots.some(sl => sl.hosts && sl.hosts.length > 0);

      const rows: { name: string; slots: RowSlot[] }[] = [];
      for (const name of siteNames) {
        const row: RowSlot[] = [];
        for (const slot of slots) {
          const siteSlot = (slot.sites || []).find(s => s.name === name);

          if (hasHosts) {
            // Aggregate from hosts belonging to this site
            const nameUpper = name.toUpperCase();
            const siteHosts = (slot.hosts || []).filter(h =>
              siteFromHost(h.name) === nameUpper
            );
            if (siteHosts.length > 0) {
              // Sum host resources for accurate site totals
              let cores_a = 0, cores_c = 0, ram_a = 0, ram_c = 0, disk_a = 0, disk_c = 0;
              const compAgg: Record<string, { available: number; capacity: number }> = {};
              for (const h of siteHosts) {
                cores_a += h.cores_available;
                cores_c += h.cores_capacity;
                ram_a += h.ram_available;
                ram_c += h.ram_capacity;
                disk_a += h.disk_available;
                disk_c += h.disk_capacity;
                if (h.components) {
                  for (const [ck, cv] of Object.entries(h.components)) {
                    if (!compAgg[ck]) compAgg[ck] = { available: 0, capacity: 0 };
                    compAgg[ck].available += cv.available;
                    compAgg[ck].capacity += cv.capacity;
                  }
                }
              }
              row.push({
                name,
                cores_available: cores_a, cores_capacity: cores_c,
                ram_available: ram_a, ram_capacity: ram_c,
                disk_available: disk_a, disk_capacity: disk_c,
                components: compAgg,
              });
              continue;
            }
          }
          // Fallback to site-level data
          row.push(siteSlot || { ...emptySlot, name });
        }
        rows.push({ name, slots: row });
      }

      // Apply filters
      const filtered = hasAnyFilter ? rows.filter(r => passesFilters(r.slots, ft)) : rows;

      const groups: RowGroup[] = [{ site: '', rows: filtered, isGroup: false }];
      return { groups, slots, totalRows: filtered.length };
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calendarData, showMode, hasAnyFilter, filterTypes, ft.model, ft.cores, ft.ram, ft.disk]);

  const interval = calendarData?.interval || calInterval;
  const numSlots = slots.length;

  // Site names from props for the finder dropdown
  const propSiteNames = useMemo(() => sites.map(s => s.name).sort(), [sites]);

  if (calError && !calendarData) {
    return (
      <div className="rc-container">
        <div className="rc-empty">{calError} <button onClick={loadCalendar} style={{ marginLeft: 8 }}>Retry</button></div>
      </div>
    );
  }

  return (
    <div className="rc-container">
      {/* Finder toggle */}
      <div className="rc-finder-toggle" onClick={() => setFinderOpen(o => !o)}>
        <span className={`rc-chevron ${finderOpen ? 'open' : ''}`}>{'\u25B6'}</span>
        Find Available Resources
      </div>

      {/* Finder panel */}
      {finderOpen && (
        <div className="rc-finder">
          <div className="rc-finder-form">
            <div className="rc-finder-field">
              <label>Cores</label>
              <input type="number" min={1} value={fCores} onChange={e => setFCores(e.target.value ? Number(e.target.value) : '')} placeholder="Any" />
            </div>
            <div className="rc-finder-field">
              <label>RAM (GB)</label>
              <input type="number" min={1} value={fRam} onChange={e => setFRam(e.target.value ? Number(e.target.value) : '')} placeholder="Any" />
            </div>
            <div className="rc-finder-field">
              <label>Disk (GB)</label>
              <input type="number" min={1} value={fDisk} onChange={e => setFDisk(e.target.value ? Number(e.target.value) : '')} placeholder="Any" />
            </div>
            <div className="rc-finder-field">
              <label>Component</label>
              <select value={fGpu} onChange={e => setFGpu(e.target.value)}>
                <option value="None">None</option>
                {Object.entries(COMPONENT_MODELS).map(([type, models]) => (
                  <optgroup key={type} label={type}>
                    {models.map(m => <option key={m} value={m}>{COMPONENT_DISPLAY[m] || m}</option>)}
                  </optgroup>
                ))}
              </select>
            </div>
            <div className="rc-finder-field">
              <label>Site</label>
              <select value={fSite} onChange={e => setFSite(e.target.value)}>
                <option value="">Any</option>
                {propSiteNames.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <button className="rc-finder-btn" onClick={handleFind} disabled={finderLoading}>
              {finderLoading ? 'Searching...' : 'Find'}
            </button>
          </div>

          {/* Results */}
          {nextResult && (
            <div className="rc-finder-results">
              {nextResult.available_now.length > 0 && (
                <>
                  <h4>Available Now</h4>
                  <div>
                    {nextResult.available_now.map(a => (
                      <span key={a.site} className="rc-available-badge" title={`${a.cores_available} cores, ${a.ram_available} GB RAM`}>
                        {a.site}
                      </span>
                    ))}
                  </div>
                </>
              )}
              {nextResult.available_soon.length > 0 && (
                <>
                  <h4>Available Soon</h4>
                  <div>
                    {nextResult.available_soon.map(a => (
                      <span key={a.site}>
                        <span className="rc-available-badge soon">{a.site}</span>
                        <span className="rc-soon-detail">
                          {formatDateTime(a.earliest_time)}
                          {a.freeing_slices.length > 0 && ` (${a.freeing_slices.map(s => s.name).join(', ')} expiring)`}
                        </span>
                      </span>
                    ))}
                  </div>
                </>
              )}
              {nextResult.not_available.length > 0 && (
                <>
                  <h4>Not Available</h4>
                  <div>
                    {nextResult.not_available.map(a => (
                      <span key={a.site} className="rc-available-badge unavailable" title={a.reason}>
                        {a.site}
                      </span>
                    ))}
                  </div>
                </>
              )}

              {/* Alternatives */}
              {altResult && altResult.alternatives.length > 0 && (
                <div className="rc-alternatives">
                  <h4>Alternatives for {altResult.preferred_site}</h4>
                  <div>
                    {altResult.alternatives.map((alt, i) => (
                      <div key={i} className="rc-alternative-card">
                        <span className="rc-alt-type">{alt.type.replace(/_/g, ' ')}</span>
                        <span className="rc-alt-site">{alt.site}</span>
                        {alt.available_now !== undefined && (
                          <span className="rc-alt-detail">{alt.available_now ? 'Available now' : 'Unavailable'}</span>
                        )}
                        {alt.cores_available !== undefined && (
                          <span className="rc-alt-detail">{alt.cores_available} cores, {alt.ram_available} GB</span>
                        )}
                        {alt.suggestion && <span className="rc-alt-detail">{alt.suggestion}</span>}
                        {alt.earliest_time && <span className="rc-alt-detail">Available: {formatDateTime(alt.earliest_time)}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Schedule Submission toggle */}
      <div className="rc-finder-toggle" onClick={() => setSchedOpen(o => !o)}>
        <span className={`rc-chevron ${schedOpen ? 'open' : ''}`}>{'\u25B6'}</span>
        Schedule Submission
      </div>

      {schedOpen && (
        <div className="rc-finder">
          <div className="rc-finder-form">
            <div className="rc-finder-field">
              <label>Slice</label>
              <select value={schedSlice} onChange={e => setSchedSlice(e.target.value)} style={{ width: 160 }}>
                <option value="">-- Select slice --</option>
                {slices.map(s => <option key={s.id || s.name} value={s.name}>{s.name}</option>)}
              </select>
            </div>
            <div className="rc-finder-field">
              <label>Scheduled Time</label>
              <input type="datetime-local" value={schedTime} onChange={e => setSchedTime(e.target.value)} style={{ width: 180 }} />
            </div>
            <div className="rc-finder-field">
              <label>Duration (hrs)</label>
              <input type="number" min={1} max={720} value={schedDuration} onChange={e => setSchedDuration(Number(e.target.value) || 24)} />
            </div>
            <div className="rc-finder-field" style={{ justifyContent: 'center' }}>
              <label>Auto-submit</label>
              <input type="checkbox" checked={schedAutoSubmit} onChange={e => setSchedAutoSubmit(e.target.checked)} style={{ width: 'auto' }} />
            </div>
            <button className="rc-finder-btn" onClick={handleSchedule} disabled={schedLoading || !schedSlice || !schedTime}>
              {schedLoading ? 'Scheduling...' : 'Schedule'}
            </button>
          </div>

          {/* Reservation list */}
          {reservations.length > 0 && (
            <div className="rc-finder-results" style={{ marginTop: 8 }}>
              <h4>Reservations</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {reservations.map(r => (
                  <div key={r.id} className="rc-alternative-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
                    <span style={{ fontWeight: 600 }}>{r.slice_name}</span>
                    <span style={{ color: 'var(--fabric-text-muted)', fontSize: 10 }}>
                      {formatDateTime(r.scheduled_time)}
                    </span>
                    <span className={`rc-available-badge ${r.status === 'pending' ? 'soon' : r.status === 'active' ? '' : 'unavailable'}`}>
                      {r.status}
                    </span>
                    {r.error && <span style={{ color: '#e25241', fontSize: 10 }}>{r.error}</span>}
                    {r.status === 'pending' && (
                      <button
                        style={{ fontSize: 10, padding: '1px 6px', cursor: 'pointer', border: '1px solid var(--fabric-border)', borderRadius: 3, background: 'transparent', color: 'var(--fabric-text)' }}
                        onClick={() => handleCancelReservation(r.id)}
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Toolbar */}
      <div className="rc-toolbar">
        <button onClick={loadCalendar} disabled={calLoading}>
          {calLoading ? 'Loading...' : '\u21BB Refresh'}
        </button>
        <div className="rc-toggle-group">
          <button className={`rc-toggle-btn ${showMode === 'sites' ? 'active' : ''}`} onClick={() => setShowMode('sites')}>Sites</button>
          <button className={`rc-toggle-btn ${showMode === 'hosts' ? 'active' : ''}`} onClick={() => setShowMode('hosts')}>Hosts</button>
        </div>
        <select
          value={calInterval}
          onChange={e => setCalInterval(e.target.value as 'hour' | 'day' | 'week')}
          style={{ fontSize: 11, padding: '2px 4px' }}
        >
          {INTERVAL_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select
          value={calDays}
          onChange={e => setCalDays(Number(e.target.value))}
          style={{ fontSize: 11, padding: '2px 4px' }}
        >
          <option value={7}>7 days</option>
          <option value={14}>14 days</option>
          <option value={30}>30 days</option>
        </select>
        <button
          className={`rc-filter-toggle-btn ${filterOpen ? 'active' : ''} ${hasAnyFilter ? 'has-filter' : ''}`}
          onClick={() => setFilterOpen(o => !o)}
        >
          {'\u2699'} Filters{hasAnyFilter ? ` (${[filterTypes.size || filterModel ? 1 : 0, filterCores ? 1 : 0, filterRam ? 1 : 0, filterDisk ? 1 : 0].reduce((a, b) => a + b, 0)})` : ''}
        </button>
        {hasAnyFilter && (
          <button
            className="rc-filter-clear-btn"
            onClick={() => { setFilterTypes(new Set()); setFilterModel(''); setFilterCores(''); setFilterRam(''); setFilterDisk(''); }}
            title="Clear all filters"
          >
            {'\u2715'}
          </button>
        )}
        {calLoading && <span className="rc-loading">Loading calendar...</span>}
        {calError && <span className="rc-loading" style={{ color: '#e25241' }}>{calError}</span>}
        <span className="rc-loading">{numSlots > 0 ? `${numSlots} ${interval} slots` : ''}</span>
      </div>

      {/* Filter bar */}
      {filterOpen && (
        <div className="rc-filter-bar">
          <div className="rc-finder-field">
            <label>Component Types</label>
            <div className="rc-checkbox-group">
              {COMPONENT_TYPES.map(t => (
                <label key={t} className="rc-checkbox-label">
                  <input
                    type="checkbox"
                    checked={filterTypes.has(t)}
                    onChange={e => {
                      const next = new Set(filterTypes);
                      if (e.target.checked) next.add(t); else next.delete(t);
                      setFilterTypes(next);
                      setFilterModel('');
                    }}
                  />
                  {t}
                </label>
              ))}
            </div>
          </div>
          <div className="rc-finder-field">
            <label>Model</label>
            <select value={filterModel} onChange={e => setFilterModel(e.target.value)} style={{ width: 160 }}>
              <option value="">Any</option>
              {filterTypes.size > 0
                ? Array.from(filterTypes).map(type => (
                    <optgroup key={type} label={type}>
                      {(COMPONENT_MODELS[type] || []).map(m => (
                        <option key={m} value={m}>{COMPONENT_DISPLAY[m] || m}</option>
                      ))}
                    </optgroup>
                  ))
                : Object.entries(COMPONENT_MODELS).map(([type, models]) => (
                    <optgroup key={type} label={type}>
                      {models.map(m => <option key={m} value={m}>{COMPONENT_DISPLAY[m] || m}</option>)}
                    </optgroup>
                  ))
              }
            </select>
          </div>
          <div className="rc-finder-field">
            <label>Color by</label>
            <select value={colorBy} onChange={e => setColorBy(e.target.value)}>
              <option value="cores">Cores</option>
              <option value="ram">RAM</option>
              <option value="disk">Disk</option>
              {COMPONENT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="rc-finder-field">
            <label>Min Cores</label>
            <input type="number" min={1} value={filterCores} onChange={e => setFilterCores(e.target.value ? Number(e.target.value) : '')} placeholder="Any" />
          </div>
          <div className="rc-finder-field">
            <label>Min RAM (GB)</label>
            <input type="number" min={1} value={filterRam} onChange={e => setFilterRam(e.target.value ? Number(e.target.value) : '')} placeholder="Any" />
          </div>
          <div className="rc-finder-field">
            <label>Min Disk (GB)</label>
            <input type="number" min={1} value={filterDisk} onChange={e => setFilterDisk(e.target.value ? Number(e.target.value) : '')} placeholder="Any" />
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="rc-legend">
        <span className="rc-legend-label">{colorBy === 'cores' ? 'Core' : colorBy === 'ram' ? 'RAM' : colorBy === 'disk' ? 'Disk' : colorBy} utilization:</span>
        <span className="rc-legend-item"><span className="rc-legend-swatch" style={{ background: 'var(--fabric-success, #008e7a)' }} />&lt;50%</span>
        <span className="rc-legend-item"><span className="rc-legend-swatch" style={{ background: 'var(--fabric-warning, #ff8542)' }} />50-75%</span>
        <span className="rc-legend-item"><span className="rc-legend-swatch" style={{ background: '#e07020' }} />75-90%</span>
        <span className="rc-legend-item"><span className="rc-legend-swatch" style={{ background: 'var(--fabric-danger, #b00020)' }} />&gt;90%</span>
        <span className="rc-legend-item"><span className="rc-legend-swatch" style={{ background: 'var(--fabric-bg-muted, #333)' }} />No data</span>
      </div>

      {/* Heatmap grid */}
      {!calendarData && calLoading ? (
        <div className="rc-empty">Loading resource calendar...</div>
      ) : totalRows === 0 && !calLoading ? (
        <div className="rc-empty">{hasAnyFilter ? `No ${showMode} match the active filters` : 'No site data available'}</div>
      ) : (
        <div className="rc-timeline" style={{ overflowX: 'auto' }}>
          <div
            className="rc-timeline-grid"
            style={{
              gridTemplateColumns: `${showMode === 'hosts' ? '200px' : '140px'} repeat(${numSlots}, minmax(${interval === 'hour' ? '28px' : '48px'}, 1fr))`,
              gridTemplateRows: `auto repeat(${totalRows}, minmax(${showMode === 'hosts' ? '24px' : '28px'}, auto))`,
            }}
          >
            {/* Header row */}
            <div className="rc-corner" />
            {slots.map((slot, i) => (
              <div key={i} className="rc-day-label" title={`${slot.start} \u2013 ${slot.end}`}>
                {formatSlotLabel(slot.start, interval)}
              </div>
            ))}

            {/* Rows — iterate groups */}
            {groups.map((group) => {
              const isCollapsed = collapsedSites.has(group.site);
              const toggleCollapse = () => setCollapsedSites(prev => {
                const next = new Set(prev);
                if (next.has(group.site)) next.delete(group.site);
                else next.add(group.site);
                return next;
              });

              return (
                <React.Fragment key={group.site || '__sites'}>
                  {/* Site group header (only in host mode) */}
                  {group.isGroup && (
                    <>
                      <div className="rc-site-label rc-group-header" onClick={toggleCollapse} style={{ cursor: 'pointer' }}>
                        <span>
                          <span className={`rc-chevron ${isCollapsed ? '' : 'open'}`}>{'\u25B6'}</span>
                          {' '}{group.site}
                          <span className="rc-host-count">{group.rows.length}</span>
                        </span>
                      </div>
                      {/* Empty cells spanning the header row */}
                      {slots.map((_, si) => (
                        <div key={si} className="rc-day-cell rc-group-header-cell" onClick={toggleCollapse} style={{ cursor: 'pointer' }} />
                      ))}
                    </>
                  )}

                  {/* Data rows (hidden when collapsed) */}
                  {(!group.isGroup || !isCollapsed) && group.rows.map(({ name, slots: rowSlots }) => {
                    const first = rowSlots[0];
                    const getUtil = (s: RowSlot) => {
                      if (colorBy === 'ram') return s.ram_capacity > 0 ? Math.max(0, Math.min(1, 1 - s.ram_available / s.ram_capacity)) : 0;
                      if (colorBy === 'disk') return s.disk_capacity > 0 ? Math.max(0, Math.min(1, 1 - s.disk_available / s.disk_capacity)) : 0;
                      if (colorBy !== 'cores') return componentUtil(s, colorBy);
                      return coreUtil(s);
                    };
                    const currentUtil = first ? getUtil(first) : 0;
                    const hasCap = (s: RowSlot) => {
                      if (colorBy === 'ram') return s.ram_capacity > 0;
                      if (colorBy === 'disk') return s.disk_capacity > 0;
                      if (colorBy !== 'cores') return hasComponentType(s, colorBy);
                      return s.cores_capacity > 0;
                    };

                    // Component badges for the label
                    const compBadges: string[] = [];
                    if (first) {
                      for (const type of COMPONENT_TYPES) {
                        if (hasComponentType(first, type)) compBadges.push(type);
                      }
                    }

                    const displayName = group.isGroup ? name.split('.')[0] : name;
                    const utilLabel = colorBy === 'cores'
                      ? `${first?.cores_available ?? 0}/${first?.cores_capacity ?? 0} cores free`
                      : colorBy === 'ram'
                        ? `${first?.ram_available ?? 0}/${first?.ram_capacity ?? 0} GB RAM free`
                        : colorBy === 'disk'
                          ? `${first?.disk_available ?? 0}/${first?.disk_capacity ?? 0} GB disk free`
                          : `${colorBy} utilization: ${Math.round(currentUtil * 100)}%`;

                    return (
                      <React.Fragment key={name}>
                        <div className={`rc-site-label ${group.isGroup ? 'rc-host-label' : ''}`}>
                          <span className="rc-label-text">
                            {displayName}
                            {compBadges.length > 0 && (
                              <span className="rc-comp-badges">
                                {compBadges.map(b => (
                                  <span key={b} className={`rc-comp-badge rc-comp-${b.toLowerCase()}`} title={b}>{b[0]}</span>
                                ))}
                              </span>
                            )}
                          </span>
                          <div className="rc-util-bar">
                            <div
                              className="rc-util-fill"
                              style={{ width: `${currentUtil * 100}%`, background: utilColor(currentUtil) }}
                              title={utilLabel}
                            />
                          </div>
                        </div>

                        {rowSlots.map((slotData, si) => {
                          const u = getUtil(slotData);
                          const hasData = hasCap(slotData);
                          const bg = hasData ? utilColor(u) : 'var(--fabric-bg-muted, #333)';
                          const tipText = `${name} \u2014 ${formatSlotLabel(slots[si]?.start || '', interval)}\nCores: ${slotData.cores_available}/${slotData.cores_capacity} free\nRAM: ${slotData.ram_available}/${slotData.ram_capacity} GB free\nDisk: ${slotData.disk_available}/${slotData.disk_capacity} GB free${componentTooltip(slotData)}`;
                          return (
                            <div
                              key={si}
                              className="rc-day-cell rc-heatmap-cell"
                              style={{ background: bg, opacity: hasData ? 0.85 : 0.3 }}
                              onMouseEnter={e => setTooltip({ x: e.clientX, y: e.clientY, text: tipText })}
                              onMouseMove={e => setTooltip({ x: e.clientX, y: e.clientY, text: tipText })}
                              onMouseLeave={() => setTooltip(null)}
                            />
                          );
                        })}
                      </React.Fragment>
                    );
                  })}
                </React.Fragment>
              );
            })}
          </div>
        </div>
      )}

      {/* Tooltip */}
      {tooltip && (
        <div className="rc-tooltip" style={{ left: tooltip.x + 12, top: tooltip.y - 10 }}>
          {tooltip.text}
        </div>
      )}
    </div>
  );
}
