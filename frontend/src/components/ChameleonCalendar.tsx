'use client';
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import * as api from '../api/client';
import type { ChameleonCalendarData } from '../api/client';
import type { ChameleonSite, ChameleonLease } from '../types/chameleon';
import '../styles/resource-calendar.css';

interface ChameleonCalendarProps {
  sites: ChameleonSite[];
  onCreateLease?: (startDate?: string) => void;
}

function formatDay(d: Date): string {
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

// Chameleon green color scheme
const CHI_GREEN = '#39B54A';
const CHI_ORANGE = '#ff8542';

type CalendarSiteData = ChameleonCalendarData['sites'][number];

export default function ChameleonCalendar({ sites, onCreateLease }: ChameleonCalendarProps) {
  const [calendarData, setCalendarData] = useState<ChameleonCalendarData | null>(null);
  const [calLoading, setCalLoading] = useState(false);
  const [calError, setCalError] = useState('');

  // Finder state
  const [finderOpen, setFinderOpen] = useState(false);
  const [fSite, setFSite] = useState('');
  const [fNodeType, setFNodeType] = useState('');
  const [fNodeCount, setFNodeCount] = useState(1);
  const [fDurationHours, setFDurationHours] = useState(24);
  const [finderLoading, setFinderLoading] = useState(false);
  const [finderResult, setFinderResult] = useState<{ earliest_start: string | null; available_now: number; total: number; error: string } | null>(null);

  // Node types for selected site
  const [nodeTypes, setNodeTypes] = useState<Array<{ node_type: string; total: number; reservable: number; cpu_arch: string }>>([]);
  const [nodeTypesLoading, setNodeTypesLoading] = useState(false);

  // Tooltip
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);

  const timelineRef = useRef<HTMLDivElement>(null);

  // Configured sites for finder dropdown
  const configuredSites = useMemo(() => sites.filter(s => s.configured), [sites]);

  // Set default site when sites load
  useEffect(() => {
    if (!fSite && configuredSites.length > 0) {
      setFSite(configuredSites[0].name);
    }
  }, [configuredSites, fSite]);

  // Fetch node types when site changes
  useEffect(() => {
    if (!fSite) { setNodeTypes([]); return; }
    setNodeTypesLoading(true);
    api.getChameleonNodeTypes(fSite)
      .then(data => {
        setNodeTypes(data.node_types || []);
        if (data.node_types?.length && !fNodeType) {
          setFNodeType(data.node_types[0].node_type);
        }
      })
      .catch(() => setNodeTypes([]))
      .finally(() => setNodeTypesLoading(false));
  }, [fSite]);

  // Fetch calendar data
  const loadCalendar = useCallback(async () => {
    setCalLoading(true);
    setCalError('');
    try {
      const data = await api.getChameleonScheduleCalendar(14);
      setCalendarData(data);
    } catch (err: unknown) {
      setCalError(err instanceof Error ? err.message : 'Failed to load calendar');
    } finally {
      setCalLoading(false);
    }
  }, []);

  useEffect(() => { loadCalendar(); }, [loadCalendar]);

  // Finder search
  const handleFind = useCallback(async () => {
    if (!fSite || !fNodeType) return;
    setFinderLoading(true);
    setFinderResult(null);
    try {
      const result = await api.findChameleonAvailability({
        site: fSite,
        node_type: fNodeType,
        node_count: fNodeCount,
        duration_hours: fDurationHours,
      });
      setFinderResult(result);
    } catch (err: unknown) {
      setFinderResult({ earliest_start: null, available_now: 0, total: 0, error: err instanceof Error ? err.message : 'Search failed' });
    } finally {
      setFinderLoading(false);
    }
  }, [fSite, fNodeType, fNodeCount, fDurationHours]);

  // Sorted sites from calendar data
  const sortedSites = useMemo(() => {
    if (!calendarData) return [];
    return [...calendarData.sites].sort((a, b) => a.name.localeCompare(b.name));
  }, [calendarData]);

  // Time range
  const rangeStart = calendarData ? new Date(calendarData.time_range.start).getTime() : 0;
  const rangeEnd = calendarData ? new Date(calendarData.time_range.end).getTime() : 0;
  const rangeDuration = rangeEnd - rangeStart;
  const now = Date.now();

  // Day columns
  const days = useMemo(() => {
    if (!rangeDuration) return [];
    const result: Date[] = [];
    const d = new Date(rangeStart);
    d.setHours(0, 0, 0, 0);
    const end = new Date(rangeEnd);
    while (d <= end) {
      result.push(new Date(d));
      d.setDate(d.getDate() + 1);
    }
    return result;
  }, [rangeStart, rangeEnd, rangeDuration]);

  const numDays = days.length;

  // Bar position calculator
  const barStyle = useCallback((lease: ChameleonLease) => {
    if (!rangeDuration) return null;
    const leaseStart = new Date(lease.start_date).getTime();
    const leaseEnd = new Date(lease.end_date).getTime();
    const barStart = Math.max(leaseStart, rangeStart);
    const barEnd = Math.min(leaseEnd, rangeEnd);
    if (barEnd <= barStart) return null;
    const left = ((barStart - rangeStart) / rangeDuration) * 100;
    const width = ((barEnd - barStart) / rangeDuration) * 100;
    if (width < 0.1) return null;
    return { left: `${left}%`, width: `${width}%` };
  }, [rangeStart, rangeEnd, rangeDuration]);

  // Bar CSS class based on lease status
  const barClass = useCallback((lease: ChameleonLease) => {
    const s = lease.status.toUpperCase();
    if (s === 'TERMINATED' || s === 'DELETED') return 'rc-bar past';
    if (s === 'PENDING' || s === 'STARTING') return 'rc-bar expiring'; // uses orange
    return 'rc-bar'; // ACTIVE uses default color
  }, []);

  // Tooltip text for a lease bar
  const barTooltipText = useCallback((lease: ChameleonLease) => {
    const resDesc = lease.reservations.length > 0
      ? lease.reservations.map(r => `${r.resource_type || 'compute'} (${r.min}-${r.max})`).join(', ')
      : 'No reservations';
    return `${lease.name}\nSite: ${lease._site}\nStatus: ${lease.status}\nStart: ${formatDateTime(lease.start_date)}\nEnd: ${formatDateTime(lease.end_date)}\n${resDesc}`;
  }, []);

  // Now-line position
  const nowLeft = rangeDuration ? ((now - rangeStart) / rangeDuration) * 100 : 0;
  const showNowLine = nowLeft >= 0 && nowLeft <= 100;

  if (calError && !calendarData) {
    return (
      <div className="rc-container" style={{ '--rc-bar-color': CHI_GREEN } as React.CSSProperties}>
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
              <label>Site</label>
              <select value={fSite} onChange={e => { setFSite(e.target.value); setFNodeType(''); setFinderResult(null); }} style={{ width: 150 }}>
                <option value="">-- select --</option>
                {configuredSites.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
              </select>
            </div>
            <div className="rc-finder-field">
              <label>Node Type {nodeTypesLoading && '(...)'}</label>
              <select value={fNodeType} onChange={e => { setFNodeType(e.target.value); setFinderResult(null); }} disabled={nodeTypesLoading || !fSite} style={{ width: 180 }}>
                <option value="">-- select --</option>
                {nodeTypes.map(nt => (
                  <option key={nt.node_type} value={nt.node_type}>
                    {nt.node_type} ({nt.reservable}/{nt.total})
                  </option>
                ))}
              </select>
            </div>
            <div className="rc-finder-field">
              <label>Nodes</label>
              <input type="number" min={1} max={100} value={fNodeCount} onChange={e => setFNodeCount(Number(e.target.value) || 1)} style={{ width: 60 }} />
            </div>
            <div className="rc-finder-field">
              <label>Duration (hrs)</label>
              <input type="number" min={1} max={168} value={fDurationHours} onChange={e => setFDurationHours(Number(e.target.value) || 1)} style={{ width: 70 }} />
            </div>
            <button
              className="rc-finder-btn"
              onClick={handleFind}
              disabled={finderLoading || !fSite || !fNodeType}
              style={{ background: CHI_GREEN }}
            >
              {finderLoading ? 'Searching...' : 'Find'}
            </button>
          </div>

          {/* Results */}
          {finderResult && (
            <div className="rc-finder-results">
              {finderResult.error ? (
                <div style={{ color: '#e25241', fontSize: 11 }}>{finderResult.error}</div>
              ) : finderResult.earliest_start === 'now' ? (
                <div>
                  <span className="rc-available-badge" style={{ background: CHI_GREEN }}>
                    Available now ({finderResult.available_now} nodes)
                  </span>
                  {onCreateLease && (
                    <button
                      className="rc-finder-btn"
                      style={{ marginLeft: 8, background: CHI_GREEN, fontSize: 10, padding: '2px 10px' }}
                      onClick={() => onCreateLease()}
                    >
                      Reserve Now
                    </button>
                  )}
                </div>
              ) : finderResult.earliest_start ? (
                <div>
                  <span className="rc-available-badge soon">
                    Available from {formatDateTime(finderResult.earliest_start)}
                  </span>
                  <span className="rc-soon-detail">
                    ({finderResult.available_now}/{finderResult.total} free now)
                  </span>
                  {onCreateLease && (
                    <button
                      className="rc-finder-btn"
                      style={{ marginLeft: 8, background: CHI_ORANGE, fontSize: 10, padding: '2px 10px' }}
                      onClick={() => onCreateLease(finderResult.earliest_start!)}
                    >
                      Reserve at that time
                    </button>
                  )}
                </div>
              ) : (
                <div style={{ color: 'var(--fabric-text-muted)', fontSize: 11 }}>No availability found in the requested window.</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Toolbar */}
      <div className="rc-toolbar">
        <button onClick={loadCalendar} disabled={calLoading}>
          {calLoading ? 'Loading...' : '\u21BB Refresh'}
        </button>
        {calLoading && <span className="rc-loading">Loading calendar...</span>}
        {calError && <span className="rc-loading" style={{ color: '#e25241' }}>{calError}</span>}
        <span className="rc-loading">{numDays > 0 ? `${numDays} days` : ''}</span>
      </div>

      {/* Timeline */}
      {!calendarData && calLoading ? (
        <div className="rc-empty">Loading Chameleon schedule calendar...</div>
      ) : sortedSites.length === 0 && !calLoading ? (
        <div className="rc-empty">No site data available. Configure Chameleon sites in Settings.</div>
      ) : (
        <div className="rc-timeline" ref={timelineRef}>
          <div
            className="rc-timeline-grid"
            style={{
              gridTemplateColumns: `140px repeat(${numDays}, 1fr)`,
              gridTemplateRows: `auto repeat(${sortedSites.length}, minmax(28px, auto))`,
            }}
          >
            {/* Header row */}
            <div className="rc-corner" />
            {days.map((d, i) => (
              <div key={i} className="rc-day-label">{formatDay(d)}</div>
            ))}

            {/* Site rows */}
            {sortedSites.map((site) => {
              const nodeTypeSummary = site.node_types
                .map(nt => `${nt.reservable}/${nt.total} ${nt.node_type}`)
                .join(', ');
              return (
                <React.Fragment key={site.name}>
                  {/* Label */}
                  <div className="rc-site-label">
                    <span>{site.name}</span>
                    {site.node_types.length > 0 && (
                      <span style={{ fontSize: 9, color: 'var(--fabric-text-muted)', fontWeight: 400 }} title={nodeTypeSummary}>
                        {site.node_types[0].reservable}/{site.node_types[0].total} {site.node_types[0].node_type}
                        {site.node_types.length > 1 && ` +${site.node_types.length - 1}`}
                      </span>
                    )}
                  </div>

                  {/* Day cells */}
                  {days.map((_, di) => (
                    <div key={di} className="rc-day-cell" />
                  ))}
                </React.Fragment>
              );
            })}
          </div>

          {/* Absolute-positioned bar overlay on top of the grid */}
          <ChameleonBarOverlay
            sites={sortedSites}
            days={days}
            rangeStart={rangeStart}
            rangeDuration={rangeDuration}
            now={now}
            barStyle={barStyle}
            barClass={barClass}
            barTooltipText={barTooltipText}
            setTooltip={setTooltip}
            showNowLine={showNowLine}
            nowLeft={nowLeft}
            timelineRef={timelineRef}
          />
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

/* --- Bar overlay: positions bars absolutely over the CSS grid --- */
interface ChameleonBarOverlayProps {
  sites: CalendarSiteData[];
  days: Date[];
  rangeStart: number;
  rangeDuration: number;
  now: number;
  barStyle: (lease: ChameleonLease) => { left: string; width: string } | null;
  barClass: (lease: ChameleonLease) => string;
  barTooltipText: (lease: ChameleonLease) => string;
  setTooltip: (t: { x: number; y: number; text: string } | null) => void;
  showNowLine: boolean;
  nowLeft: number;
  timelineRef: React.RefObject<HTMLDivElement | null>;
}

function ChameleonBarOverlay({
  sites, days, rangeDuration,
  barStyle, barClass, barTooltipText,
  setTooltip, showNowLine, nowLeft, timelineRef,
}: ChameleonBarOverlayProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState<{ headerH: number; labelW: number; rowH: number; totalW: number } | null>(null);

  // Measure grid dimensions after render
  useEffect(() => {
    const el = timelineRef.current;
    if (!el) return;
    const grid = el.querySelector('.rc-timeline-grid') as HTMLElement | null;
    if (!grid) return;

    const measure = () => {
      const corner = grid.querySelector('.rc-corner') as HTMLElement;
      const firstLabel = grid.querySelector('.rc-site-label') as HTMLElement;
      if (!corner || !firstLabel) return;
      const headerH = corner.offsetHeight;
      const labelW = firstLabel.offsetWidth;
      const rowH = firstLabel.offsetHeight;
      const totalW = grid.scrollWidth;
      setDims({ headerH, labelW, rowH, totalW });
    };

    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(grid);
    return () => ro.disconnect();
  }, [timelineRef, sites.length, days.length]);

  if (!dims || !rangeDuration) return null;

  const timelineWidth = dims.totalW - dims.labelW;

  return (
    <div
      ref={overlayRef}
      style={{
        position: 'absolute',
        top: 0,
        left: dims.labelW,
        width: timelineWidth,
        height: dims.headerH + sites.length * dims.rowH,
        pointerEvents: 'none',
      }}
    >
      {/* Now line */}
      {showNowLine && (
        <div
          className="rc-now-line"
          style={{ left: `${nowLeft}%`, top: dims.headerH }}
        />
      )}

      {/* Bars per site */}
      {sites.map((site, si) => {
        const topOffset = dims.headerH + si * dims.rowH;
        return site.leases.map((lease) => {
          const style = barStyle(lease);
          if (!style) return null;

          // Determine bar color based on lease status
          const status = lease.status.toUpperCase();
          let barBg: string | undefined;
          if (status === 'ACTIVE') barBg = CHI_GREEN;
          else if (status === 'PENDING' || status === 'STARTING') barBg = CHI_ORANGE;
          // past/terminated uses the .past class (gray) from CSS

          return (
            <div
              key={`${site.name}-${lease.id}`}
              className={barClass(lease)}
              style={{
                ...style,
                top: topOffset + 3,
                height: dims.rowH - 6,
                pointerEvents: 'auto',
                ...(barBg ? { background: barBg } : {}),
              }}
              onMouseEnter={(e) => setTooltip({ x: e.clientX, y: e.clientY, text: barTooltipText(lease) })}
              onMouseMove={(e) => setTooltip({ x: e.clientX, y: e.clientY, text: barTooltipText(lease) })}
              onMouseLeave={() => setTooltip(null)}
            />
          );
        });
      })}
    </div>
  );
}
